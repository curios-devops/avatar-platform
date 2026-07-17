# Incremental fix over lhm-worker:v1.
#
# v1 shipped without pytorch3d: LHM's install_cu121.sh tried to compile it
# from source, which fails under qemu ("No CUDA runtime is found") and the
# script kept going. Install Facebook's prebuilt wheel instead — it matches
# the base stack exactly (torch 2.3.0 / cu121 / py3.10) and needs no compile.
# --no-index makes pip fail loudly rather than fall back to an sdist build.
#
# Build:  docker build --platform linux/amd64 \
#           -f docker/lhm_worker.incremental.Dockerfile \
#           -t devopsavatar/lhm-worker:v2 .
FROM devopsavatar/lhm-worker:v1

RUN pip install --no-cache-dir fvcore iopath \
 && pip install --no-cache-dir --no-index --no-deps pytorch3d \
    -f https://dl.fbaipublicfiles.com/pytorch3d/packaging/wheels/py310_cu121_pyt230/download.html \
 && python -c "import pytorch3d; print('pytorch3d', pytorch3d.__version__)"
