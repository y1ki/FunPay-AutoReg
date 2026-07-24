# FunPay Auto Registration

Автоматическая регистрация аккаунтов на FunPay.com через AdsPower + Anti-Captcha.

## Требования

- Python 3.9+
- AdsPower (запущенный, с API на localhost:50325)
- Ключ anti-captcha.com

## Установка

```bash
pip install loguru playwright
playwright install chromium
```

## Файлы

| Файл | Описание |
|------|----------|
| `main.py` | Скрипт регистрации |
| `proxies.txt` | Прокси (формат: `ip:port:username:password`) |
| `mail.txt` | Почтовые аккаунты (формат: `login:pass`) |
| `acc.txt` | Сохранённые аккаунты (username:pass:email:pass) |
| `accounts/*.json` | Куки после регистрации |

## Настройка

1. Вставь ключ от anti-captcha.com в Config в main.py:
```python
anti_captcha_api_key: str = "твой_ключ"
```

2. Добавь прокси в `proxies.txt`:
```
ip:port:login:pass
```

3. Добавь почты в `mail.txt`:
```
login@rambler.ru:password
```

## Запуск

```bash
python main.py
```

Скрипт спросит сколько аккаунтов регать. Регает по одному последовательно.

## Процесс регистрации

1. Создаётся профиль в AdsPower с прокси
2. Открывается https://funpay.com/en/account/register
3. Принимаются cookie
4. Заполняются: username, email, пароль
5. Отмечается чекбокс соглашения
6. Решается Cloudflare Turnstile через anti-captcha.com
7. Отправляется форма
8. Если есть письмо активации — ссылка открывается в браузере
9. Аккаунт сохраняется в `acc.txt`
10. Профиль удаляется из AdsPower

## Формат сохранения

```
username:password:email:email_password
```

## Примечания

- `KEEP_OPEN = False` — браузер закрывается автоматически
- `delete_profile_after_use = True` — профили AdsPower удаляются после использования
- Почта удаляется из `mail.txt` после успешной регистрации

---

<div align="center">
<br>
<b>y1ki</b>
<br>
<a href="https://t.me/y1kiLOLZ">@y1kiLOLZ</a>
<br><br>
<em>with love, y1ki</em>
</div>
