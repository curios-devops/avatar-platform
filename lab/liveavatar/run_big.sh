#!/bin/bash
# Renders the being's side of a live call (the FlashHead server's tape: her speech AND her silences while she listens)
# with the engines that cannot hold a call on one GPU: EchoMimicV3-Flash and LiveAvatar. Same portrait, same audio.
#   bash run_big.sh /workspace/in/call.wav        (SEC=15 by default; SKIP_EM=1 / SKIP_LA=1 to skip one)
# Wall times go to /workspace/out/times.jsonl (load + generation; the logs have the per-block split).
set -uo pipefail
W=/workspace; IN=$W/in; O=$W/out; L=$W/logs; mkdir -p $O
CALL=${1:-$IN/call.wav}; SEC=${SEC:-15}
ffmpeg -loglevel error -y -i "$CALL" -t $SEC -ar 16000 -ac 1 $IN/call_cut.wav
rec(){ echo "{\"engine\":\"$1\",\"wall_s\":$2,\"audio_s\":$SEC,\"ok\":$3}" >> $O/times.jsonl; echo "[$(date +%T)] $1 $2 s ok=$3"; }
PROMPT="A Latina woman with a short dark wavy bob and a charcoal sweatshirt sits at a wooden desk in her home tech studio \
(ring light, podcast microphone, monitor with code). She talks to the camera like a friendly tech creator explaining a new \
gadget: natural head and shoulder movement, expressive hand gestures, lively facial expressions; when she is silent she \
listens with small nods and calm breathing."

if [ -z "${SKIP_EM:-}" ]; then
  t0=$(date +%s); F=$(( SEC * 25 )); F=$(( F - (F - 1) % 4 ))
  ( cd $W/em && . .venv/bin/activate && python infer_flash.py --image_path $IN/ada.png --audio_path $IN/call_cut.wav \
      --prompt "$PROMPT" --num_inference_steps 8 \
      --config_path config/config.yaml --model_name $W/models/em/Wan2.1-Fun-V1.1-1.3B-InP --ckpt_idx 50000 \
      --transformer_path $W/models/em/echomimicv3-flash-pro/diffusion_pytorch_model.safetensors --save_path $O/em_ada \
      --wav2vec_model_dir $W/models/em/chinese-wav2vec2-base --sampler_name Flow_Unipc --video_length $F \
      --guidance_scale 6.0 --audio_guidance_scale 3.0 --audio_scale 1.0 --neg_scale 1.0 --neg_steps 0 --seed 43 \
      --enable_teacache --teacache_threshold 0.1 --num_skip_start_steps 5 --riflex_k 6 --ulysses_degree 1 --ring_degree 1 \
      --weight_dtype bfloat16 --sample_size ${EM_H:-768} ${EM_W:-512} --fps 25 --add_prompt '' --negative_prompt '' --shift 5.0 \
    && cp "$(ls -t $O/em_ada/*.mp4 | grep -v tmp | head -1)" $O/echomimic_ada.mp4 ) > $L/run_em.log 2>&1
  rec echomimic $(( $(date +%s) - t0 )) $([ -f $O/echomimic_ada.mp4 ] && echo true || echo false)
fi

if [ -z "${SKIP_LA:-}" ]; then
  t0=$(date +%s)
  ( cd $W/la && . .venv/bin/activate && ENABLE_COMPILE=${LA_COMPILE:-false} torchrun --nproc_per_node=1 --master_port=29101 \
      minimal_inference/s2v_streaming_interact.py --ulysses_size 1 --task s2v-14B --size "${LA_SIZE:-832*480}" \
      --base_seed 420 --training_config liveavatar/configs/s2v_causal_sft.yaml --offload_model ${LA_OFFLOAD:-False} \
      --convert_model_dtype --prompt "$PROMPT" --image $IN/ada.png --audio $IN/call_cut.wav --infer_frames 48 \
      --load_lora --lora_path_dmd "Quark-Vision/Live-Avatar" --sample_steps 4 --sample_guide_scale 0 --num_clip 10000 \
      --num_gpus_dit 1 --sample_solver euler --single_gpu --ckpt_dir ckpt/Wan2.2-S2V-14B/ \
      --save_file $O/liveavatar_ada.mp4 ${LA_FP8:+--fp8} ) > $L/run_la.log 2>&1
  rec liveavatar $(( $(date +%s) - t0 )) $(ls $O/liveavatar_ada*.mp4 > /dev/null 2>&1 && echo true || echo false)
fi
