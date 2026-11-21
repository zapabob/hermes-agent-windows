<div dir="rtl">

# ہرمیس ایجنٹ — Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB">King's English</a> ·
  <a href="README.ja.md" lang="ja">日本語</a> ·
  <a href="README.zh-CN.md" lang="zh-CN">简体中文</a> ·
  <a href="README.es.md" lang="es">Español</a> ·
  <a href="README.ur-pk.md" lang="ur-PK"><strong>اردو</strong></a>
</p>

> [!NOTE]
> انگریزی [`README.md`](README.md) بنیادی اور مستند تعارف ہے۔ تمام زبانوں کے
> صفحات ایک ہی مصنوعات کی حدود اور تنصیب کا طریقہ بیان کرتے ہیں۔

**[Hermes Agent](https://github.com/NousResearch/hermes-agent) کا غیر سرکاری
downstream، جو ہمیشہ چلنے والے Windows ورک اسٹیشن کے لیے ڈھالا گیا ہے۔**
Electron Desktop، CLI، پیغام رسانی Gateway، پروفائلز، مقامی inference،
semantic memory اور automation ایک ہی source tree اور core میں فراہم ہوتے ہیں۔

اس downstream کی آزادانہ دیکھ بھال
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows)
میں ہوتی ہے۔ Nous Research سے کوئی وابستگی یا توثیق نہیں۔ upstream کی نسبت اور
[MIT لائسنس](LICENSE) برقرار ہیں۔

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

**ماخذ ورژن: 0.24.0** (`2026.11.22`) · چینلز: `stable`, `preview`

## بنیادی سہولتیں

| سطح | کام |
| --- | --- |
| CLI | گفتگو، setup، tools، skills اور تشخیص |
| Electron Desktop | native chat، پروفائلز، Security Center، Bot Mode اور Git panes |
| Gateway | Telegram، Discord، Slack، LINE، Signal اور دیگر پر مسلسل پیغام رسانی |
| TUI | stdio JSON-RPC پر Ink ٹرمینل انٹرفیس |
| مقامی inference | remote providers کے ساتھ llama.cpp/GGUF |
| Automation | cron، skills، MCP، delegation اور kanban |

اضافی صلاحیتیں plugins، skills اور MCP جیسے کنارے کے اجزا میں رہتی ہیں، تاکہ
ہر model call کے ساتھ بھیجا جانے والا بنیادی toolset غیر ضروری طور پر نہ بڑھے۔

## نیا: RustXNG کے ذریعے ویب تلاش

شامل شدہ `web-rustxng` plugin، Hermes کے موجودہ `web_search` tool کو آپ کے
اپنے RustXNG metasearch server سے جوڑتا ہے۔ تازہ معلومات کے لیے Hermes ویب
تلاش استعمال کرتا ہے؛ زیادہ باقاعدہ source verification کے لیے profile کے
prompt میں اضافی ہدایت بھی دی جا سکتی ہے۔ یہ ہر پیغام پر خودکار تلاش نہیں
کرتا۔ RustXNG صرف تلاش کرتا ہے؛ صفحے کا متن حاصل کرنے کے لیے الگ provider
درکار ہے۔

source checkout سے RustXNG تیار کرنے کے لیے:

<div dir="ltr">

```powershell
git submodule update --init plugins/rustxng
cargo build --manifest-path plugins/rustxng/Cargo.toml --locked --release
.\plugins\rustxng\target\release\rustxng.exe --profile standard --bind 127.0.0.1 --port 8888
```

</div>

Hermes CLI یا Gateway شروع کرنے والے environment میں
`RUSTXNG_URL=http://127.0.0.1:8888` مقرر کریں، پھر فعال profile میں search
backend منتخب کریں:

<div dir="ltr">

```powershell
uv run hermes config set web.search_backend rustxng
```

</div>

مکمل مراحل، search smoke test اور prompt ہدایت کے لیے
[RustXNG integration guide](plugins/web/rustxng/README.md) دیکھیں۔ ابتدا میں
`standard` profile استعمال کریں۔ RustXNG اپنے profile میں فعال upstream
providers کو تلاش کی query بھیجتا ہے؛ query میں secrets یا نجی گفتگو شامل نہ
کریں۔ جب تک network deployment الگ سے محفوظ نہ ہو، service کو صرف
`127.0.0.1` پر bind رکھیں۔ دوسرے profiles فعال کرنے سے پہلے ہر source کی
شرائط دیکھیں؛ ذاتی استعمال ان شرائط سے مستثنیٰ نہیں کرتا۔

## فوری تنصیب

درکار چیزیں: Windows 11 x64، PowerShell، Git،
[`uv`](https://docs.astral.sh/uv/) اور Python 3.11–3.13۔ source سے Desktop
بنانے کے لیے Node.js بھی درکار ہے۔

<div dir="ltr">

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

</div>

| مقصد | رہنمائی |
| --- | --- |
| اسی checkout سے Desktop کھولیں | `uv run hermes desktop` |
| Installer یا portable ZIP | [Releases](https://github.com/zapabob/hermes-agent-windows/releases)، پہلے `SHA256SUMS.txt` کی تصدیق کریں |
| Windows تنصیب | [`docs/windows/INSTALL.md`](docs/windows/INSTALL.md) |
| اختیاری integrations | [`docs/windows/INTEGRATIONS.md`](docs/windows/INTEGRATIONS.md) |

`main` پر push ہونا stable installer کی اشاعت کا ثبوت نہیں۔ secrets فعال
profile میں رکھیں؛ tokens، session databases یا model weights commit نہ کریں۔

## حدود اور حفاظت

- Desktop backend کے lifecycle کا ایک ہی مالک ہے۔
- تباہ کن تبدیلیوں کے لیے منظوری اور بحالی کا راستہ ضروری ہے۔
- پروفائلز، credentials، sessions اور Gateway state الگ تھلگ رکھیں۔
- ویب تلاش کے نتائج بیرونی اور غیر معتبر مواد ہیں۔
- Hermes Agent کا اصل منصوبہ Nous Research کا ہے؛ اس downstream کی ریلیز،
  مدد اور جانچ کے دعوے الگ طور پر اسی repository میں برقرار رکھے جاتے ہیں۔

## مزید دستاویزات

- [بنیادی انگریزی تعارف](README.md) · [日本語](README.ja.md) ·
  [简体中文](README.zh-CN.md) · [Español](README.es.md)
- [Windows تنصیب](docs/windows/INSTALL.md) ·
  [RustXNG](plugins/web/rustxng/README.md) · [Security](SECURITY.md)
- [Downstream پالیسی](DOWNSTREAM_POLICY.md) ·
  [خصوصیات کا ریکارڈ](FEATURES.yaml) · [برقرار رکھے گئے patches](CARRY.yaml)

## لائسنس اور نسبت

Hermes Agent کو Nous Research نے MIT License کے تحت بنایا ہے۔ یہ downstream
اصل نسبت، copyright اور contributor history برقرار رکھتا ہے اور اسی
[MIT License](LICENSE) کے تحت دستیاب ہے۔

</div>
