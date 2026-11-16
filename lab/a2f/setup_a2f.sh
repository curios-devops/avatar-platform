#!/bin/bash
# Round 4: NVIDIA Audio2Face-3D SDK (MIT) + Audio2Face-3D v3.0 (NVIDIA Open Model License) on a RunPod pod.
# Image runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04 (CUDA 12.8 toolkit). TensorRT 10.13 comes
# from NVIDIA's public tarball (headers, libs and trtexec), nothing gated. Inputs in /workspace/in:
# a2f_dump.cpp and the 16 kHz wavs. Output: /workspace/out/*.csv + timings.txt.
set -e
nohup sh -c 'sleep 3300; runpodctl remove pod $RUNPOD_POD_ID' >/dev/null 2>&1 &   # in-pod self-stop, 55 min
T0=$(date +%s); mark() { echo "[$(( $(date +%s) - T0 ))s] $*" | tee -a /workspace/out/timings.txt; }
mkdir -p /workspace/out; cd /workspace
mark start
(curl -sL https://developer.download.nvidia.com/compute/machine-learning/tensorrt/10.13.3/tars/TensorRT-10.13.3.9.Linux.x86_64-gnu.cuda-12.9.tar.gz | tar xz) &
TRT_PID=$!
git clone -q --depth 1 https://github.com/NVIDIA/Audio2Face-3D-SDK sdk
cd sdk
./fetch_deps.sh release >/dev/null
python3 -m pip install -q "huggingface_hub[cli]" numpy
hf download nvidia/Audio2Face-3D-v3.0 --local-dir _data/audio2face-models/audio2face-3d-v3.0 >/dev/null
wait $TRT_PID; mark "deps + TensorRT + model downloaded"
export TENSORRT_ROOT_DIR=/workspace/TensorRT-10.13.3.9 CUDA_PATH=/usr/local/cuda
export PATH=$TENSORRT_ROOT_DIR/bin:$PATH LD_LIBRARY_PATH=$TENSORRT_ROOT_DIR/lib:$LD_LIBRARY_PATH
PYTHONPATH=audio2x-common/scripts:audio2face-sdk/scripts python3 -c "
import gen_sample_data as g; g.diffusion_gen_data(source_model='audio2face-3d-v3.0', custom_folder_name='multi-diffusion')"
mark "TensorRT engine built"
cp /workspace/in/a2f_dump.cpp audio2face-sdk/source/samples/sample-a2f-executor/main.cpp
./build.sh release sample-a2f-executor >/workspace/out/build.log 2>&1 || { tail -40 /workspace/out/build.log; exit 1; }
mark "SDK built"
M=_data/generated/audio2face-sdk/samples/data/multi-diffusion/model.json
for w in /workspace/in/*_16k.wav; do
  n=$(basename $w .wav)
  ./run_sample.sh ./_build/release/audio2face-sdk/bin/sample-a2f-executor $M $w /workspace/out/$n.csv 2 | tee -a /workspace/out/timings.txt
done
python3 - <<'EOF' >> /workspace/out/timings.txt
import json, numpy as np, glob
d = np.load(glob.glob('_data/audio2face-models/audio2face-3d-v3.0/bs_skin_Mark.npz')[0], allow_pickle=True)
print('npz keys', list(d.keys()))
for k in d.keys():
    if 'name' in k.lower(): json.dump([str(x) for x in d[k]], open('/workspace/out/pose_names.json', 'w'))
EOF
cp _data/audio2face-models/audio2face-3d-v3.0/bs_skin_config_Mark.json /workspace/out/
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv >> /workspace/out/timings.txt
du -sh /workspace/TensorRT-10.13.3.9 _data _build /workspace/sdk >> /workspace/out/timings.txt
mark done
