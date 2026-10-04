"""Reload the persisted adapter in a fresh process; never train or activate it."""
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import torch
from peft import PeftModel, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from frozen_evaluator import evaluate_choices
from pilot_data import check_frozen, read_items
from pilot_train import tensor_hash, backbone_identity

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "runs/pilot003"
BASE = ROOT.parent / "hakua-epistemic-r3-qlora-pilot/base_checkpoint"
logging.basicConfig(level=logging.INFO)

def main():
    identity = json.loads((ROOT / "frozen_inputs.json").read_text(encoding="utf-8"))
    check_frozen({str(ROOT / name): value for name, value in identity.items()})
    output = RUN / "artifact_reload_bounded_verification.json"
    if output.exists():
        raise RuntimeError("Refuse to overwrite prior readback")
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True, encoding="utf-8", errors="replace", check=True).stdout
    if int(gpu.strip().splitlines()[0]) < 3000:
        raise RuntimeError("Insufficient free GPU memory; no service will be stopped")
    torch.cuda.set_per_process_memory_fraction(0.16)
    torch.set_num_threads(1)
    torch.manual_seed(42)
    tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True, trust_remote_code=False)
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=False)
    model = AutoModelForCausalLM.from_pretrained(BASE, local_files_only=True, trust_remote_code=False, quantization_config=quant, device_map={"":0}, torch_dtype=torch.bfloat16, attn_implementation="sdpa")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=False)
    model = PeftModel.from_pretrained(model, RUN / "adapter", is_trainable=False)
    adapter_names = {name for name, _ in model.named_parameters() if "lora_" in name}
    expected = json.loads((RUN / "weight_change.json").read_text(encoding="utf-8"))
    loaded_tensors = {name: tensor_hash(parameter) for name, parameter in model.named_parameters() if name in adapter_names}
    actual_base = backbone_identity(model, adapter_names)
    evaluation = evaluate_choices(model, tokenizer, read_items(ROOT / "frozen_eval.jsonl")[:1], RUN / "artifact_reload_bounded_eval.json")
    child = json.loads((RUN / "child_eval.json").read_text(encoding="utf-8"))
    report = {"adapter_loaded_from_saved_bytes": True, "loaded_adapter_tensor_count": len(loaded_tensors), "loaded_adapter_tensors_match_posttrain_identity": loaded_tensors == expected["adapter_after"], "reloaded_backbone_matches_training_fingerprint": actual_base["sha256"] == expected["base_sha256_after"], "sampled_choice_matches_original_child": [x["choice"] for x in evaluation["rows"]] == [x["choice"] for x in child["rows"][:1]], "actual_eval_count":len(evaluation["rows"]), "adapter_sha256": hashlib.sha256((RUN / "adapter/adapter_model.safetensors").read_bytes()).hexdigest(), "scope": "Fresh-process reload verifies every adapter tensor and the base fingerprint, plus one deterministic first-item forward. Not an all72 repeat evaluation or an independent capability experiment", "activation": "STOP_AND_REPORT", "training_performed": False}
    check_frozen({str(ROOT / name): value for name, value in identity.items()})
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    logging.info("Artifact reload result: %s", report)
    if not all(report[k] for k in ["loaded_adapter_tensors_match_posttrain_identity", "reloaded_backbone_matches_training_fingerprint", "sampled_choice_matches_original_child"]):
        raise RuntimeError("Artifact readback mismatch")

if __name__ == "__main__":
    main()
