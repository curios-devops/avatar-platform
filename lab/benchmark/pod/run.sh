#!/bin/bash
# Runs every engine on every case with the same portrait and audio; times each run (model load included, since a new
# call pays it) and keeps the log. Output: /workspace/out/<engine>_<case>.mp4 and /workspace/out/times.jsonl
W=/workspace; IN=$W/in; O=$W/out; mkdir -p $O
gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
run(){ # engine case cmd...
  local e=$1 c=$2; shift 2
  local t0=$(date +%s.%N)
  ( "$@" ) > $W/logs/run_${e}_${c}.log 2>&1; local rc=$?
  local t1=$(date +%s.%N); local vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  local dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $O/${e}_${c}.mp4 2>/dev/null)
  echo "{\"engine\":\"$e\",\"case\":\"$c\",\"rc\":$rc,\"wall_s\":$(echo "$t1 - $t0" | bc),\"video_s\":\"${dur:-0}\",\"gpu\":\"$gpu\",\"vram_after_mb\":$vram}" | tee -a $O/times.jsonl
}
for c in ${CASES:-imani nueva}; do
  for m in ${FH_MODELS:-lite pro}; do
    run flashhead_$m $c bash -c "cd $W/fh && . .venv/bin/activate && python generate_video.py --ckpt_dir $W/models/SoulX-FlashHead-1_3B \
      --wav2vec_dir $W/models/wav2vec2-base-960h --model_type $m --cond_image $IN/$c.png --audio_path $IN/$c.wav \
      --audio_encode_mode stream --save_file $O/flashhead_${m}_${c}.mp4"
  done
  if [ -z "${SKIP_EM:-}" ]; then
    run echomimic $c bash -c "cd $W/em && . .venv/bin/activate && python infer_flash.py --image_path $IN/$c.png --audio_path $IN/$c.wav \
      --prompt 'A person is speaking to the camera, natural expressions, subtle head movement.' --num_inference_steps 8 \
      --config_path config/config.yaml --model_name $W/models/em/Wan2.1-Fun-V1.1-1.3B-InP --ckpt_idx 50000 \
      --transformer_path $W/models/em/echomimicv3-flash-pro/diffusion_pytorch_model.safetensors --save_path $O/em_$c \
      --wav2vec_model_dir $W/models/em/chinese-wav2vec2-base --sampler_name Flow_Unipc --video_length ${EM_FRAMES:-321} \
      --guidance_scale 6.0 --audio_guidance_scale 3.0 --audio_scale 1.0 --neg_scale 1.0 --neg_steps 0 --seed 43 \
      --enable_teacache --teacache_threshold 0.1 --num_skip_start_steps 5 --riflex_k 6 --ulysses_degree 1 --ring_degree 1 \
      --weight_dtype bfloat16 --sample_size 512 512 --fps 25 --add_prompt '' --negative_prompt '' --shift 5.0 \
      && cp \$(ls -t $O/em_$c/*.mp4 | grep -v tmp | head -1) $O/echomimic_$c.mp4"
  fi
done
