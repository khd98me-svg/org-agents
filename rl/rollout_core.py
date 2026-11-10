"""حلقة الحلقة الواحدة (episode) مستقلة عن أي مكتبة تدريب: تأخذ دالة chat(messages)->نص الرد، وتعيد المحادثة والمكافأة.
هذا الجزء مُختبَر محلياً. دفتر Colab يلفّه فقط بواجهة ART."""
import portal_env as P


async def run_episode(chat, seed, max_tokens=300):
    env = P.PortalEnv(seed)
    msgs = [{"role": "system", "content": P.SYSTEM},
            {"role": "user", "content": P.TASK + "\n\nالصفحة الحالية:\n" + env.snapshot()}]
    replies = []
    while not env.finished:
        text = await chat(list(msgs))
        replies.append(text)
        msgs.append({"role": "assistant", "content": text})
        obs, done = env.step(text)
        if done:
            break
        msgs.append({"role": "user", "content": obs})
    return msgs, replies, env.reward(), env
