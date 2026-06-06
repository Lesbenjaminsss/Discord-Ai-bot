"""python token_kontrol.py"""
from settings import ENV_PATH, check_token, get_token

t = get_token()
ok, msg = check_token(t)
print(msg)
print(f".env: {ENV_PATH}")
if ok:
    print("Baslat: python bot.py")
else:
    raise SystemExit(1)
