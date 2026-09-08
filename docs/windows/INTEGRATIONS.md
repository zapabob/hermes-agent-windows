# Optional integrations

This inventory was retained from the previous README. Presence in this list is not a current-head Windows qualification result. Consult the plug-in manifest and initialise only the integrations you need.


Hermes discovers standard directory plug-ins through `plugin.yaml`,
`__init__.py`, and `register(ctx)`. The 51 bundled standard root plug-ins are
grouped below; `lmcache` is also shipped as a legacy manifest with its own
registration path. Run `uv run hermes plugins` to see what is enabled for the
active profile.

| Area | Bundled root plug-ins |
| --- | --- |
| Agents and operations | `ai-employee-org`, `ai-partner-os`, `airi`, `aituber-onair`, `aituber-kit`, `book-to-skill`, `desktop-dashboard`, `disk-cleanup`, `freebuff`, `freellmapi`, `google-colab`, `google_meet`, `hermes-gpt`, `hermes-bot-mode`, `line-ai-bot`, `lm-twitterer`, `memory-llm-wiki`, `notebooklm`, `oh-my-hermes`, `openclaw-vendor`, `openmanus`, `plugin-doctor`, `research-desk`, `scrapling-feeds`, `teams_pipeline`, `warashibe-reselling` |
| Media, voice and XR | `akari-video`, `buzz`, `fish-audio-tts`, `hakua-tts-bridge`, `heygen`, `hyperframes`, `irodori-tts`, `questframe-fh6vr`, `sillytavern`, `spotify`, `unity-cli`, `unity-vrchat-bridge`, `unsloth-studio`, `voicebox`, `voicevox-tts`, `vrchat-autonomy` |
| Knowledge, security and OSINT | `osint-agent`, `security-guidance`, `semantic-graph`, `shinka-osint`, `sitdeck-osint`, `surfsense`, `tookie-osint`, `world-intel-osint`, `worldmonitor-osint` |
| Legacy manifest | `lmcache` |

The repository contains 154 plug-in manifests in total. Specialised discovery
families are kept separate so that only configured capabilities enter a
session.

| Discovery family | Included providers/adapters |
| --- | --- |
| Browser (3) | `browser_use`, `browserbase`, `firecrawl` |
| Cron (1) | `chronos` |
| Dashboard authentication (4) | `basic`, `drain`, `nous`, `self_hosted` |
| Image generation (7) | `deepinfra`, `fal`, `krea`, `openai`, `openai-codex`, `openrouter`, `xai` |
| Memory (9) | `byterover`, `ebbinghaus`, `hindsight`, `holographic`, `honcho`, `mem0`, `openviking`, `retaindb`, `supermemory` |
| Model providers (42) | `actual`, `ai-gateway`, `alibaba`, `alibaba-coding-plan`, `anthropic`, `arcee`, `azure-foundry`, `bedrock`, `commandcode`, `copilot`, `copilot-acp`, `custom`, `deepinfra`, `deepseek`, `fireworks`, `freebuff`, `freellmapi`, `gemini`, `gmi`, `huggingface`, `hypura`, `kilocode`, `kimi-coding`, `meta-ai`, `minimax`, `nebius-token-factory`, `nous`, `novita`, `nvidia`, `ollama-cloud`, `openai-codex`, `opencode-free`, `opencode-zen`, `openrouter`, `qwen-oauth`, `router`, `stepfun`, `upstage`, `vertex`, `xai`, `xiaomi`, `zai` |
| Observability (1) | `langfuse` |
| Messaging platforms (22) | `a2a`, `buzz`, `dingtalk`, `discord`, `email`, `feishu`, `google_chat`, `homeassistant`, `irc`, `line`, `matrix`, `mattermost`, `ntfy`, `photon`, `raft`, `simplex`, `slack`, `sms`, `teams`, `telegram`, `wecom`, `whatsapp` |
| Video generation (3) | `deepinfra`, `fal`, `xai` |
| Web search/extraction (11) | `brave_free`, `cloakbrowser`, `ddgs`, `exa`, `firecrawl`, `keenable`, `parallel`, `scrapling`, `searxng`, `tavily`, `xai` |

Git submodules are optional integrations. Initialise all of them only when you
need their features: `git submodule update --init --recursive`.

| Path | Repository | Purpose |
| --- | --- | --- |
| `plugins/hermes-bot-mode/desktop` | [Hermes-Bot-Mode](https://github.com/zapabob/Hermes-Bot-Mode.git) | Desktop bot roster UI |
| `vendor/openclaw-mirror/AI-Scientist` | [AI-Scientist](https://github.com/zapabob/AI-Scientist.git) | Scientific-agent vendor mirror |
| `vendor/openclaw-mirror/ATLAS` | [ATLAS](https://github.com/zapabob/ATLAS.git) | Research-agent vendor mirror |
| `vendor/openclaw-mirror/ShinkaEvolve` | [ShinkaEvolve](https://github.com/zapabob/ShinkaEvolve.git) | Evolution workflow vendor mirror |
| `vendor/neuro-sdk` | [neuro-sdk](https://github.com/zapabob/neuro-sdk.git) | Neuro integration SDK |
| `vendor/openmanus` | [OpenManus](https://github.com/zapabob/OpenManus.git) | OpenManus runtime |
| `vendor/SillyTavern` | [SillyTavern](https://github.com/zapabob/SillyTavern.git) | Local character-chat frontend |
| `vendor/shinka-osint` | [ShinkaEvolve-OSINT](https://github.com/zapabob/ShinkaEvolve-OSINT.git) | OSINT analysis runtime |
| `vendor/buzz` | [buzz](https://github.com/zapabob/buzz.git) | Speech transcription runtime |
| `vendor/officecli` | [OfficeCLI](https://github.com/zapabob/OfficeCLI.git) | Office document command-line tools |
| `vendor/akari-video` | [akari-video](https://github.com/zapabob/akari-video.git) | AI video editor |
| `vendor/cloakbrowser` | [cloakbrowser](https://github.com/zapabob/cloakbrowser.git) | Browser automation runtime |
| `vendor/airi` | [airi](https://github.com/zapabob/airi.git) | Avatar and companion runtime |
| `vendor/oh-my-hermes` | [oh-my-hermes](https://github.com/zapabob/oh-my-hermes.git) | Hermes workflow extension |
| `vendor/OpenMausBot` | [OpenMausBot](https://github.com/zapabob/OpenMausBot.git) | Desktop automation bot |
| `vendor/heygen-cli` | [heygen-cli](https://github.com/heygen-com/heygen-cli.git) | HeyGen command-line client |

