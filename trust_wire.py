"""Replace CycleKernal random trust with evidence measurements."""

def evidence_snapshot(failures, runs):
    if runs == 0:
        return {"S": None, "orientation": "unmeasured", "above_cone": False}
    p = failures / runs
    S = p * (1 - p)
    if failures == 0:
        orient = "pass"
    elif failures == runs:
        orient = "fail"
    else:
        orient = "mixed"
    return {"S": S, "orientation": orient, "above_cone": S > 0.25}

# Drop-in replacement for random.uniform(0.6, 0.95)
def measured_trust(failures, runs):
    snap = evidence_snapshot(failures, runs)
    return snap["S"] if snap["S"] is not None else 0.0

if __name__ == "__main__":
    for f, r in [(0,100),(1,40),(3,100)]:
        s = evidence_snapshot(f, r)
        print(f"{f}/{r}: S={s['S']:.4f} {s['orientation']} above_cone={s['above_cone']}")
