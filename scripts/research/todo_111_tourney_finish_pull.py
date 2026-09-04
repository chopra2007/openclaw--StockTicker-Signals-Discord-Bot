"""TODO #111 tournament — finish the remaining leg downloads, one at a time.

The parallel downloader in todo_111_tourney_pull.py stalled part-way through a
large batch, so this runs the same cost-estimated, ceiling-checked `buy()` one
request at a time with retries and visible progress. It buys nothing that is
already on disk and it obeys the same $20 run ceiling.

Usage:  python3 -u scripts/research/todo_111_tourney_finish_pull.py <allowance>
"""
from __future__ import annotations
import glob, hashlib, json, os, socket, sys, time

# The provider sometimes stops sending part-way through a chunked response and
# the socket read then blocks forever — a SIGALRM does not interrupt it. A
# default socket timeout does, because urllib3 honours it on every read.
socket.setdefaulttimeout(45)

sys.path.insert(0, "scripts/research")
import todo_111_tourney_pull as P
import databento as db

TOURNEY = "/home/openclaw/.openclaw/research-data/todo-111-tournament"
# Sealed chain snapshots are structural only — they say where the strikes are.
# No sealed OUTCOME is read by this script; that is todo_111_tourney_sealed.py.
MANIFESTS = ("manifest_dev_legs", "events_manifest_legs", "manifest_sealed")
DEADLINE_S = 150        # a single-contract request runs 3-25s; this is generous


def sweep_parts():
    """Drop half-written files left by an interrupted download."""
    for p in glob.glob(f"{TOURNEY}/legs/*.part") + glob.glob(f"{TOURNEY}/chains/*.part"):
        os.remove(p)


CHUNK = 1       # one contract per request; anything larger stalls server-side


def split(job) -> list:
    """Break a many-contract request into small ones.

    A nine-contract, fourteen-day request stalls part-way through every time,
    while a one- or two-contract request of the same span returns in seconds.
    Billing is by delivered bytes, so asking in smaller pieces costs the same.
    """
    syms = job["kw"]["symbols"]
    if len(syms) <= CHUNK:
        return [job]
    out = []
    for i in range(0, len(syms), CHUNK):
        part = syms[i:i + CHUNK]
        kw = dict(job["kw"], symbols=part)
        h = hashlib.sha1(("|".join(part) + str(kw["end"])).encode()).hexdigest()[:10]
        out.append(dict(job, symbols=part, kw=kw,
                        label=f"{job['label']} part{i // CHUNK + 1}",
                        path=f"{TOURNEY}/legs/legs_{job['day']}_{h}.dbn.zst"))
    return out


def _child(job):
    """Run one purchase. Lives in its own process so a stalled read can be killed."""
    import databento as dbx
    P.buy(dbx.Historical(key=P.key()), job["label"], job["path"], **job["kw"])


def fetch_in_child(job) -> bool:
    """One purchase, with a deadline the parent can actually enforce.

    The provider stops sending part-way through a chunked response often enough
    to matter, and the socket read then blocks forever: neither a SIGALRM nor a
    default socket timeout interrupts it, because the client sets its own
    per-request timeout of None. Killing a child process does.
    """
    import multiprocessing as mp
    p = mp.Process(target=_child, args=(job,))
    p.start()
    p.join(DEADLINE_S)
    if p.is_alive():
        p.terminate()
        p.join(10)
        if p.is_alive():
            p.kill()
        return False
    return p.exitcode == 0 and os.path.exists(job["path"])


def main(allowance: float):
    client = db.Historical(key=P.key())
    start = P.spent_all()
    print(f"starting run total ${start:.4f}, allowance ${allowance:.2f}", flush=True)
    for name in MANIFESTS:
        man = json.load(open(f"{TOURNEY}/{name}.json"))
        jobs = [q for j in P.plan(man, P.rebuild_owned_index()) for q in split(j)]
        jobs = [j for j in jobs if not os.path.exists(j["path"])]
        print(f"== {name}: {len(jobs)} requests still needed ==", flush=True)
        for n, j in enumerate(jobs, 1):
            if P.spent_all() - start > allowance:
                print(f"  STOP: ${allowance:.2f} allowance used up", flush=True)
                return
            t0 = time.time()
            for attempt in (1, 2, 3):
                if fetch_in_child(j):
                    break
                sweep_parts()
                print(f"  retry {attempt} {j['label']}: stalled", flush=True)
                time.sleep(2 * attempt)
            else:
                print(f"  GAVE UP on {j['label']}", flush=True)
            if n % 5 == 0 or n == len(jobs):
                print(f"  {n}/{len(jobs)}  last {time.time()-t0:.1f}s  "
                      f"run total ${P.spent_all():.4f}", flush=True)
    print(f"ALL DONE  run total ${P.spent_all():.4f}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 1.20)
