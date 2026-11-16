// Round 4 (Jasom): Audio2Face-3D v3.0 (diffusion) + blendshape solve, offline over a 16 kHz wav.
// Writes one CSV row per frame: t_seconds, w0..w51 (ARKit-ordered skin poses of the model's bs config),
// and prints the time the executor took, so the arena can report real speed.
//   a2f_dump <model.json> <in_16k.wav> <out.csv> [identity=2 (Claire 0, James 1, Mark 2)] [gpu=0|1 blendshape solver]
// Replaces the body of sample-a2f-executor/main.cpp so it builds with the SDK's own CMake target.
#include "audio2face/audio2face.h"
#include "audio2x/cuda_utils.h"
#include "AudioFile.h"
#include <cuda_runtime.h>
#include <chrono>
#include <cstdio>
#include <iostream>
#include <vector>

#define CHECK(expr) do { auto _e = (expr); if (_e) { std::cerr << "fail line " << __LINE__ << ": " << _e.message() << std::endl; return 1; } } while (0)

struct Out { FILE* f; std::size_t frames = 0; std::size_t n = 0; };

int main(int argc, char** argv) {
  if (argc < 4) { std::cerr << "usage: a2f_dump model.json in.wav out.csv [identity]" << std::endl; return 2; }
  const std::size_t identity = argc > 4 ? std::stoul(argv[4]) : 2;
  const bool gpu = argc > 5 && argv[5][0] == '1';
  AudioFile<float> wav;
  if (!wav.load(argv[2]) || wav.getSampleRate() != 16000) { std::cerr << "need a 16 kHz wav" << std::endl; return 1; }
  const auto& audio = wav.samples[0];

  auto t0 = std::chrono::steady_clock::now();
  auto* bundle = nva2f::ReadDiffusionBlendshapeSolveExecutorBundle(
      1, argv[1], nva2f::IGeometryExecutor::ExecutionOption::SkinTongue,
      /*useGpuSolver*/ gpu, identity, /*constantNoise*/ true, nullptr, nullptr);
  if (!bundle) { std::cerr << "bundle failed" << std::endl; return 1; }
  auto t1 = std::chrono::steady_clock::now();

  auto& ex = bundle->GetExecutor();
  Out out{std::fopen(argv[3], "w")};
  out.n = ex.GetWeightCount();
  std::cout << "weights per frame: " << out.n << std::endl;
  if (gpu) {
    CHECK(ex.SetResultsCallback(
        [](void* ud, const nva2f::IBlendshapeExecutor::DeviceResults& r) {
          auto& o = *static_cast<Out*>(ud);
          std::vector<float> h(r.weights.Size());
          cudaMemcpyAsync(h.data(), r.weights.Data(), h.size() * sizeof(float), cudaMemcpyDeviceToHost, r.cudaStream);
          cudaStreamSynchronize(r.cudaStream);
          std::fprintf(o.f, "%.4f", r.timeStampCurrentFrame / 16000.0);
          for (float v : h) std::fprintf(o.f, ",%.4f", v);
          std::fprintf(o.f, "\n");
          o.frames++;
          return true;
        },
        &out));
  } else {
    CHECK(ex.SetResultsCallback(
        [](void* ud, const nva2f::IBlendshapeExecutor::HostResults& r, std::error_code ec) {
          auto& o = *static_cast<Out*>(ud);
          if (ec) return;
          std::fprintf(o.f, "%.4f", r.timeStampCurrentFrame / 16000.0);
          for (std::size_t i = 0; i < r.weights.Size(); ++i) std::fprintf(o.f, ",%.4f", r.weights.Data()[i]);
          std::fprintf(o.f, "\n");
          o.frames++;
        },
        &out));
  }

  // neutral emotion, then the whole clip
  auto& emo = bundle->GetEmotionAccumulator(0);
  std::vector<float> neutral(emo.GetEmotionSize(), 0.0f);
  CHECK(emo.Accumulate(0, nva2x::HostTensorFloatConstView{neutral.data(), neutral.size()}, bundle->GetCudaStream().Data()));
  CHECK(emo.Close());
  CHECK(bundle->GetAudioAccumulator(0).Accumulate(nva2x::HostTensorFloatConstView{audio.data(), audio.size()}, bundle->GetCudaStream().Data()));
  CHECK(bundle->GetAudioAccumulator(0).Close());

  auto t2 = std::chrono::steady_clock::now();
  while (nva2x::GetNbReadyTracks(ex) > 0) CHECK(ex.Execute(nullptr));
  CHECK(ex.Wait(0));
  auto t3 = std::chrono::steady_clock::now();
  std::fclose(out.f);

  const double audioS = audio.size() / 16000.0;
  const double runS = std::chrono::duration<double>(t3 - t2).count();
  std::printf("frames %zu, audio %.2f s, load %.2f s, run %.2f s, %.1fx real time\n", out.frames, audioS,
              std::chrono::duration<double>(t1 - t0).count(), runS, audioS / runS);
  bundle->Destroy();
  return 0;
}
