"""يولّد أمثلة تعليمية (ملف JSONL) من الحل اليدوي لتدريب إشرافي قصير قبل التعلم المعزز (بداية دافئة)."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portal_env as P

n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
with open("demos.jsonl", "w", encoding="utf-8") as f:
    for seed in range(10_000, 10_000 + n):
        env = P.PortalEnv(seed); log = []
        r = P.expert_policy(env, log)
        msgs = [{"role": "system", "content": P.SYSTEM}, {"role": "user", "content": P.TASK + "\n\nالصفحة الحالية:\n" + env.__class__(seed).snapshot()}]
        for raw, obs in log:
            msgs.append({"role": "assistant", "content": raw}); msgs.append({"role": "user", "content": obs})
        f.write(json.dumps({"messages": msgs[:-1], "reward": r}, ensure_ascii=False) + "\n")
print("تم: %d مثال في demos.jsonl" % n)
