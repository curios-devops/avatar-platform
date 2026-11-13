"""LiveTalking test pod on the NEW RunPod account (RUNPOD_K_API_KEY). Key read from backend/.env, never printed.
    python3 pod.py create            pod from the base image (setup.sh installs everything, ~7 min)
    ../../../backend/.venv/bin/python pod.py create-image   pod from devopsavatar/meya-livetalking (~1-2 min); the
                                     avatars come from R2 through presigned URLs (3 h), missing ones are generated
                                     from their clip and saved back. MAX_SECONDS (default 4500) = the pod's self-stop.
    python3 pod.py status
    python3 pod.py watchdog <id>     terminates the pod when spend >= CAP (polls every 30 s)
    python3 pod.py terminate <id>
"""
import json, pathlib, sys, time, urllib.error, urllib.request
ROOT = pathlib.Path("/Users/mac/Documents/avatar-platform")
ENV = dict(l.split("=", 1) for l in (ROOT / "backend/.env").read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
KEY = ENV["RUNPOD_K_API_KEY"].strip().strip('"')
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "User-Agent": "meya-bench/0.1"}
HERE = pathlib.Path(__file__).parent
CAP = float(__import__("os").environ.get("CAP", "0.95"))  # USD this watchdog allows (env CAP)

def req(url, data=None, method=None):
    r = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None, H, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as f:
            return f.status, json.loads(f.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:600].decode(errors="replace")

def gql(q):
    return req("https://api.runpod.io/graphql", {"query": q})[1]["data"]

def balance():
    return gql("query { myself { clientBalance currentSpendPerHr } }")["myself"]

AVATARS = tuple(__import__("os").environ.get("AVATARS", "vale imani leo nova").split())
IMAGE = "devopsavatar/meya-livetalking:latest"

def r2_env():
    """Short-lived R2 links for the pod: download each avatar, or its clip plus an upload link to save it once made."""
    import boto3, botocore
    g = lambda k: ENV.get(k, "").strip().strip('"')
    s3 = boto3.client("s3", endpoint_url=f"https://{g('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com", region_name="auto",
                      aws_access_key_id=g("R2_ACCESS_KEY_ID"), aws_secret_access_key=g("R2_SECRET_ACCESS_KEY"))
    b, ttl = g("R2_BUCKET_NAME"), 3 * 3600
    link = lambda op, key: s3.generate_presigned_url(op, Params={"Bucket": b, "Key": key}, ExpiresIn=ttl)
    env = {"AVATARS": " ".join(AVATARS)}
    for a in AVATARS:
        key = f"livetalking/avatars/{a}.tgz"
        try:
            s3.head_object(Bucket=b, Key=key); env[f"AVATAR_URL_{a}"] = link("get_object", key)
        except botocore.exceptions.ClientError:
            env[f"CLIP_URL_{a}"] = link("get_object", f"livetalking/clips/{a}.mp4")
            env[f"UPLOAD_URL_{a}"] = link("put_object", key)
    print("avatars:", {a: ("R2" if f"AVATAR_URL_{a}" in env else "generate") for a in AVATARS})
    return env

def create(image=None):
    import os
    gpus = os.environ.get("GPUS", "NVIDIA GeForce RTX 3090,NVIDIA RTX A5000,NVIDIA GeForce RTX 4090,NVIDIA RTX A6000,NVIDIA A40").split(",")
    pub = pathlib.Path.home().joinpath(".ssh/runpod_a2.pub").read_text().strip()
    extra = {**r2_env(), "MAX_SECONDS": __import__("os").environ.get("MAX_SECONDS", "4500")} if image else {}
    b = balance(); (HERE / "start_balance.json").write_text(json.dumps(b)); print("saldo", round(b["clientBalance"], 4))
    for cloud in ("COMMUNITY", "SECURE"):
        s, p = req("https://rest.runpod.io/v1/pods", {
            "name": os.environ.get("NAME", "meya-livetalking"),
            "imageName": os.environ.get("IMAGE") or image or "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
            "cloudType": cloud, "gpuTypeIds": gpus, "gpuTypePriority": "custom", "gpuCount": 1,
            "containerDiskInGb": int(os.environ.get("DISK", "50")), "volumeInGb": 0,
            **({"allowedCudaVersions": os.environ["CUDA"].split(",")} if os.environ.get("CUDA") else {}),
            "ports": ["22/tcp", "8010/http"], "supportPublicIp": True, "env": {"PUBLIC_KEY": pub, **extra}})
        print(cloud, s, p if s >= 300 else {k: p.get(k) for k in ("id", "costPerHr", "machineId")})
        if s < 300:
            (HERE / "pod_id").write_text(p["id"]); (HERE / f"pod_id_{os.environ.get('NAME', 'meya-livetalking')}").write_text(p["id"]); return

def status():
    pid = (HERE / "pod_id").read_text()
    s, p = req(f"https://rest.runpod.io/v1/pods/{pid}")
    b0 = json.loads((HERE / "start_balance.json").read_text())["clientBalance"]
    b = balance()
    print(json.dumps({k: p.get(k) for k in ("id", "desiredStatus", "costPerHr", "publicIp", "portMappings", "lastStartedAt")} if isinstance(p, dict) else p),
          "gastado", round(b0 - b["clientBalance"], 4), "USD", b["currentSpendPerHr"], "$/h")

def terminate(pid):
    print("terminate", req(f"https://rest.runpod.io/v1/pods/{pid}", method="DELETE")[0])

MAX_MINUTES = int(__import__("os").environ.get("MAX_MINUTES", "40"))

def watchdog(pid):
    """Terminates the pod at CAP USD or MAX_MINUTES. A network error never ends the watch (it did once, on
    2026-11-11, and a pod ran all night): it retries, and as soon as the network is back it applies both limits."""
    b0 = json.loads((HERE / "start_balance.json").read_text())["clientBalance"]
    started = time.time()
    while True:
        try:
            if time.time() - started > MAX_MINUTES * 60:
                terminate(pid); print("tiempo máximo alcanzado"); return
            # this pod's own cost (its rate x the time it has existed), not the account's: on 2026-11-13 an
            # account-wide count let a second pod's spend trip this one's cap
            s0, p0 = req(f"https://rest.runpod.io/v1/pods/{pid}")
            rate = float(p0.get("costPerHr") or 0) if isinstance(p0, dict) else 0.0
            spent = rate * (time.time() - started) / 3600
            (HERE / f"spent_{pid}.txt").write_text(f"{time.strftime('%H:%M:%S')} {spent:.4f} (account {b0 - balance()['clientBalance']:.4f})\n")
            if spent >= CAP:
                terminate(pid); print("CAP alcanzado", spent); return
            s, p = req(f"https://rest.runpod.io/v1/pods/{pid}")
            if s == 404 or (isinstance(p, dict) and p.get("desiredStatus") in ("TERMINATED", "EXITED")):
                print("pod ya no existe"); return
        except Exception as exc:  # DNS, timeouts, sleep: keep watching
            print(time.strftime("%H:%M:%S"), "watchdog: error de red, reintento:", type(exc).__name__, flush=True)
        time.sleep(30)

if __name__ == "__main__":
    a = sys.argv[1:]
    {"create": lambda: create(), "create-image": lambda: create(IMAGE), "status": lambda: status(), "watchdog": lambda: watchdog(a[1]), "terminate": lambda: terminate(a[1])}[a[0]]()
