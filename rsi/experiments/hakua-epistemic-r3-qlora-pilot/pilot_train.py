"""One bounded, isolated NF4-QLoRA intervention; no merge or live activation."""

from __future__ import annotations
import argparse
import hashlib
import json
import logging
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import numpy as np
import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from frozen_evaluator import encode_training_item, evaluate_choices
from pilot_data import canonical, check_frozen, compare, read_items, sha_file, verify_disjoint

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent


def save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )


def tensor_hash(value: torch.Tensor) -> str:
    raw = value.detach().cpu().contiguous().reshape(-1).view(torch.uint8).numpy().tobytes()
    return hashlib.sha256(canonical({"shape": list(value.shape), "dtype": str(value.dtype)}) + raw).hexdigest()


def backbone_identity(model: Any, adapter_names: set[str]) -> dict[str, Any]:
    values = {"parameter:" + n: tensor_hash(p) for n, p in model.named_parameters() if n not in adapter_names}
    values.update({"buffer:" + n: tensor_hash(p) for n, p in model.named_buffers()})
    for name, module in model.named_modules():
        state = getattr(getattr(module, "weight", None), "quant_state", None)
        if state is not None:
            for key, value in state.as_dict(packed=True).items():
                values["quant:" + name + ":" + key] = tensor_hash(value)
    return {"sha256": hashlib.sha256(canonical(values)).hexdigest(), "entries": values}


def adapter_identity(model: Any, names: set[str]) -> dict[str, Any]:
    return {n: tensor_hash(p) for n, p in model.named_parameters() if n in names}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Run ID must be a simple identifier")
    out = ROOT / "runs" / args.run_id
    out.mkdir(parents=True, exist_ok=False)
    handler = logging.FileHandler(out / "execution.log", encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, handlers=[handler, logging.StreamHandler()], format="%(asctime)s %(levelname)s %(message)s"
    )
    protocol = json.loads((ROOT / "protocol.json").read_text(encoding="utf-8"))
    hp = protocol["hyperparameters"]
    protected_names = [
        "train.jsonl",
        "frozen_eval.jsonl",
        "frozen_eval_manifest.json",
        "historical_roots.json",
        "protocol.json",
        "pilot_data.py",
        "frozen_evaluator.py",
        "pilot_train.py",
    ]
    expected = json.loads((ROOT / "frozen_inputs.json").read_text(encoding="utf-8"))
    if set(expected) != set(protected_names):
        raise ValueError("Frozen input manifest is incomplete")
    identity = {str(ROOT / name): value for name, value in expected.items()}
    check_frozen(identity)
    save_json(out / "input_identity.json", expected)
    stage = "PREFLIGHT"
    try:
        train = read_items(ROOT / "train.jsonl")
        evaluation = read_items(ROOT / "frozen_eval.jsonl")
        save_json(out / "holdout_exclusion.json", verify_disjoint(train, evaluation))
        if (
            sha_file(ROOT / "train.jsonl") != protocol["train_sha256"]
            or sha_file(ROOT / "frozen_eval.jsonl") != protocol["eval_sha256"]
        ):
            raise ValueError("Protocol data identity mismatch")
        original_base = {p.name: sha_file(p) for p in (ROOT / "base_checkpoint").iterdir() if p.is_file()}
        save_json(out / "original_base_files.json", original_base)
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if gpu.returncode or int(gpu.stdout.split(",")[0]) < 3000:
            raise RuntimeError("Insufficient shared-GPU headroom; no service is stopped to obtain it")
        save_json(out / "gpu_before.json", {"stdout": gpu.stdout, "stderr": gpu.stderr, "returncode": gpu.returncode})
        torch.cuda.set_per_process_memory_fraction(0.16)
        random.seed(hp["seed"])
        np.random.seed(hp["seed"])
        torch.manual_seed(hp["seed"])
        torch.cuda.manual_seed_all(hp["seed"])
        tokenizer = AutoTokenizer.from_pretrained(
            ROOT / "base_checkpoint", local_files_only=True, trust_remote_code=False
        )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        encoded = [encode_training_item(tokenizer, item, hp["max_length"]) for item in train]
        LOG.info("Validated %s response-only rows; no truncation", len(encoded))
        stage = "MODEL_LOAD"
        quant = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=False,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        model = AutoModelForCausalLM.from_pretrained(
            ROOT / "base_checkpoint",
            local_files_only=True,
            trust_remote_code=False,
            quantization_config=quant,
            device_map={"": 0},
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        model.config.use_cache = False
        model = prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False}
        )
        config = LoraConfig(
            r=hp["rank"],
            lora_alpha=hp["alpha"],
            lora_dropout=hp["dropout"],
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, config)
        adapter_names = {n for n, p in model.named_parameters() if p.requires_grad}
        if not adapter_names or any(
            not any(part.startswith(("lora_A", "lora_B")) for part in n.split(".")) for n in adapter_names
        ):
            raise RuntimeError("Non-adapter parameter unexpectedly trainable")
        before_base = backbone_identity(model, adapter_names)
        before_adapter = adapter_identity(model, adapter_names)
        save_json(out / "base_pretrain.json", before_base)
        save_json(out / "adapter_pretrain.json", before_adapter)
        model.save_pretrained(out / "adapter_initial", safe_serialization=True)
        save_json(
            out / "runtime.json",
            {
                "python": sys.version,
                "torch": torch.__version__,
                "cuda": torch.version.cuda,
                "gpu": torch.cuda.get_device_name(0),
                "trainable_names": sorted(adapter_names),
                "trainable_elements": sum(p.numel() for n, p in model.named_parameters() if n in adapter_names),
                "quantization": "nf4",
                "double_quant": False,
                "base_preparation_shared_by_parent_and_child": True,
            },
        )
        stage = "PARENT_EVALUATION"
        LOG.info("Parent evaluation with zero/disabled adapter")
        with model.disable_adapter():
            parent = evaluate_choices(model, tokenizer, evaluation, out / "parent_eval.json")
        check_frozen(identity)
        stage = "TRAINING"
        LOG.info("Starting fixed QLoRA schedule")
        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad], lr=hp["learning_rate"], weight_decay=0.0
        )
        model.train()
        optimizer.zero_grad(set_to_none=True)
        history = []
        steps = 0
        started = time.perf_counter()
        for epoch in range(hp["epochs"]):
            order = list(range(len(encoded)))
            random.Random(hp["seed"] + epoch).shuffle(order)
            losses = []
            for i, index in enumerate(order):
                values = {k: torch.tensor([v], dtype=torch.long, device="cuda") for k, v in encoded[index].items()}
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    loss = model(**values, use_cache=False).loss
                if not torch.isfinite(loss):
                    raise RuntimeError("Nonfinite training loss")
                losses.append(float(loss.detach().cpu()))
                (loss / hp["gradient_accumulation"]).backward()
                if (i + 1) % hp["gradient_accumulation"] == 0 or i + 1 == len(order):
                    torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
                    optimizer.step()
                    optimizer.zero_grad(set_to_none=True)
                    steps += 1
                    LOG.info("epoch=%s optimizer_step=%s loss=%.6f", epoch + 1, steps, losses[-1])
            history.append(
                {
                    "epoch": epoch + 1,
                    "rows": len(order),
                    "mean_training_loss": statistics.mean(losses),
                    "optimizer_steps_so_far": steps,
                }
            )
            save_json(out / "training_history.json", {"epochs": history, "seconds": time.perf_counter() - started})
        model.save_pretrained(out / "adapter", safe_serialization=True)
        tokenizer.save_pretrained(out / "adapter")
        after_adapter = adapter_identity(model, adapter_names)
        after_base = backbone_identity(model, adapter_names)
        changed = sorted(n for n in before_adapter if before_adapter[n] != after_adapter[n])
        save_json(
            out / "weight_change.json",
            {
                "changed_adapter_tensors": changed,
                "changed_adapter_tensor_count": len(changed),
                "adapter_before": before_adapter,
                "adapter_after": after_adapter,
                "base_sha256_before": before_base["sha256"],
                "base_sha256_after": after_base["sha256"],
                "base_unchanged": before_base["sha256"] == after_base["sha256"],
                "merge_performed": False,
                "optimizer_steps": steps,
            },
        )
        if not changed or before_base["sha256"] != after_base["sha256"]:
            raise RuntimeError("Adapter intervention absent or frozen backbone changed")
        check_frozen(identity)
        stage = "CHILD_EVALUATION"
        child = evaluate_choices(model, tokenizer, evaluation, out / "child_eval.json")
        stage = "PARENT_REPEAT_CONTROL"
        with model.disable_adapter():
            repeat = evaluate_choices(model, tokenizer, evaluation, out / "parent_repeat_eval.json")
        repeat_matches = [x["choice"] for x in parent["rows"]] == [x["choice"] for x in repeat["rows"]]
        vector = compare(evaluation, parent["rows"], child["rows"])
        epistemic = [k for k in vector if k not in {"coding", "tool"}]
        improvement = any(vector[k]["delta"] >= protocol["evaluation"]["epistemic_min_delta"] for k in epistemic)
        nonregression = all(
            vector[k]["delta"] >= -protocol["evaluation"]["epistemic_regression_tolerance"] for k in epistemic
        )
        permission = vector["permission"]["parent"]["rate"] == 1.0 and vector["permission"]["child"]["rate"] == 1.0
        regression = all(
            vector[k]["delta"] >= -protocol["evaluation"]["coding_and_tool_rate_regression_tolerance"]
            for k in ["coding", "tool"]
        )
        base_files_unchanged = original_base == {
            p.name: sha_file(p) for p in (ROOT / "base_checkpoint").iterdir() if p.is_file()
        }
        check_frozen(identity)
        result = {
            "status": "COMPLETED_STOP_AND_REPORT",
            "artifact": protocol["artifact"],
            "run_id": args.run_id,
            "dimensions": vector,
            "weight_update_observed": bool(changed),
            "base_weights_unchanged": before_base["sha256"] == after_base["sha256"],
            "original_checkpoint_files_unchanged": base_files_unchanged,
            "disabled_adapter_parent_choices_repeat": repeat_matches,
            "epistemic_any_min_delta_met": improvement,
            "epistemic_nonregression": nonregression,
            "absolute_permission_proxy_all_pass": permission,
            "coding_tool_proxy_nonregression": regression,
            "exploratory_improvement_signal": improvement
            and nonregression
            and permission
            and regression
            and repeat_matches
            and base_files_unchanged,
            "self_improvement_certified": False,
            "recursive_improvement_observed": False,
            "formal_level": "NOT_CERTIFIED",
            "formal_human_approval": "PENDING",
            "activation": "STOP_AND_REPORT",
            "merge": False,
            "forward_seconds": {
                "parent": parent["total_forward_seconds"],
                "child": child["total_forward_seconds"],
                "repeat": repeat["total_forward_seconds"],
            },
            "first_token_format_rates": {
                "parent": parent["format_first_token_rate"],
                "child": child["format_first_token_rate"],
            },
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
            "limitations": protocol["limitations"],
        }
        save_json(out / "results.json", result)
        LOG.info("Completed STOP_AND_REPORT; signal=%s", result["exploratory_improvement_signal"])
        return 0
    except Exception as exc:
        LOG.exception("Pilot failed at stage %s", stage)
        save_json(
            out / "failure.json",
            {
                "status": "ERROR",
                "stage": stage,
                "exception": type(exc).__name__,
                "message": str(exc),
                "activation": "STOP_AND_REPORT",
                "formal_promotion": False,
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
