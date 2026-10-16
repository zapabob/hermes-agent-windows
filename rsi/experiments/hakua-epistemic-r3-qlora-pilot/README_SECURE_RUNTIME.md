# Qualified dependency migration for the frozen pilot

This entry point checks a dedicated Python environment before importing the
historical experiment. It preserves the eight files in `frozen_inputs.json`, the
historical protocol, the original checkpoint and every previous run. New runs
use the `secure1-` prefix and separate `runtime-receipts` records. Historical
replay instructions describe their original environments; they are not evidence
that a new run used repaired dependencies.

The runtime manifest records the required installed dependency closure and
critical source hashes. The pilot has its own `uv.lock`; the root Hermes lock
does not install or certify this experiment. Product and experiment version
numbers have not been raised by this migration.

## Installation into a new environment

Use native CPython 3.10 and a new writable location with sufficient free space
(allow at least 10 GB for the CUDA wheel, installation and package cache). Never
sync or update the historical `.venv-cuda` or the environment it borrowed. The
following PowerShell example is run from the repository root, uses a new
directory, and restores its process-local uv setting afterward:

```powershell
$pilotRoot = (Resolve-Path -LiteralPath 'rsi\experiments\hakua-epistemic-r3-qlora-pilot').Path
$newRoot = 'H:\HermesPilotSecure-new'
if (Test-Path -LiteralPath $newRoot) { throw 'Choose a new directory; preserve existing environments.' }
New-Item -ItemType Directory -Path $newRoot | Out-Null
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $newRoot 'env'
    uv --cache-dir (Join-Path $newRoot 'cache') sync --locked --no-dev --project $pilotRoot --python 3.10 --link-mode hardlink
    if ($LASTEXITCODE -ne 0) { throw 'Installation failed; retain the directory and log.' }
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
}
```

The named PyTorch index is explicit and used only for Torch. Other public
packages use the ordinary registry. Accelerate uses the included pure-Python
wheel and its lockfile hash. No live model server, driver or existing Python
environment is changed by this installer.

## Check before execution

```powershell
python -I -S -B "$pilotRoot\secure_runtime.py" --environment (Join-Path $newRoot 'env')
```

The default operation checks installed metadata, distribution ownership, source
hashes and frozen input identity. It does not import Torch, initialize CUDA,
train, create a run, execute `.pth` files or contact a model provider. Both the
public command and its child require `-I -S -B`; these flags must be supplied
when Python starts, before site initialization can execute. The child adds only the verified site-packages directory
when an execution is requested. Required Windows architecture variables are
preserved; provider secrets and `PYTHONPATH` are not forwarded.

Training requires an explicit command and a new identifier:

```powershell
python -I -S -B "$pilotRoot\secure_runtime.py" --environment (Join-Path $newRoot 'env') --execute --run-id secure1-new_trial_001
```

This command is a new training run, not a check-only operation. It validates the
recorded local checkpoint identity, requires the qualified CUDA backend and at
least 3000 MiB free GPU memory, and calls the unchanged trainer. The trainer
retains its 0.16 GPU memory cap, response-only masking, NF4/BF16 configuration,
adapter-only update and no-merge/no-activation behavior. Existing run IDs cannot
be reused. Begun and finished receipts preserve the child exit code, including
failure or a missing result. A zero process exit is not formal promotion.

Frozen Python modules resolve to their verified files even if an adjacent
package has the same name. Python source is compiled directly rather than
loading existing bytecode. Native extension loading remains necessary for
Torch and is not replaced. Internal execution workers use a started receipt and
per-launch stdin handshake. Each worker itself validates results and writes its
finished receipt; the parent also validates and records its supervisor outcome.
The handshake is not authentication against a caller who can write receipts.
Even with a caller-created receipt, missing or invalid results fail validation.
The Windows-only `colorama` dependency
is conditional in the runtime contract. Linux resolution remains in the lock,
but this migration's actual runtime qualification covers Windows only.

## Qualification scope

The isolated Windows qualification used CPython 3.10.11, Torch 2.13.0+cu130,
Transformers 5.17.0, PEFT 0.21.2, bitsandbytes 0.48.1 and the source-patched
Accelerate wheel. A small synthetic compatibility run exercised 168 NF4 modules,
four accumulated microsteps and one optimizer step, unchanged frozen base and
quantization metadata, adapter-only change, repeated parent logits and safe
adapter save/reload. The eight frozen files stayed unchanged and the existing
generation, embedding and watchdog services responded before and afterward.
This is functionality evidence, not a historical replay or a model-quality
equivalence claim.

The attempted bitsandbytes 0.50.2 migration was rejected: its forward path
changed frozen bias parameter dtype. Version 0.48.1 preserves the existing bias
behavior and was qualified with the repaired Torch stack. It remains pinned.

Accelerate 1.15.0+hermes.1 is a maintained local patch, not a claim that upstream
1.15.0 fixes the index traversal. Its source patch, Apache license and exact
wheel are in `vendor/`. The patch confines checkpoint shard references before
loading while preserving legitimate Hub snapshot/blob and distributed-reader
behavior. Source-bound checkpoint regression and compatibility evidence must
accompany dependency advisory results. A public-version advisory match alone
does not establish that this private patch is correct.

The source baseline is upstream Accelerate commit
`6afc1e5ee217051fde702b23de2813344dc0fd33`. Its codeload archive SHA-256 is
`31b86872bc647b288ea4713c710b47a0c3e37359e2f26e1ea14009a9e3a0a25a`.
The three-file patch changes package identity in `setup.py` and
`src/accelerate/__init__.py`, and the shared loading boundary in
`src/accelerate/utils/modeling.py`. It was built with setuptools 84.0.0 and wheel
0.48.0 using `uv build --wheel --no-build-isolation --python <dedicated-python>`.
The resulting wheel SHA-256 is
`674d973d22f4607a563648d009c482ea0c63f86d7c586210505123381c26d452`;
the patched loading owner SHA-256 is
`329f308f73851396623b21f3b075bd5ee02fd48e11c76ada28f8ed83bedb2a79`.
