# Hermes Agent Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB">King's English</a> ·
  <a href="README.ja.md" lang="ja">日本語</a> ·
  <a href="README.zh-CN.md" lang="zh-CN">简体中文</a> ·
  <a href="README.es.md" lang="es"><strong>Español</strong></a> ·
  <a href="README.ur-pk.md" lang="ur-PK">اردو</a>
</p>

> [!NOTE]
> La versión canónica en inglés es [`README.md`](README.md). Este resumen
> describe el mismo producto, límites e instalación que las otras traducciones.

**Edición downstream no oficial de [Hermes Agent](https://github.com/NousResearch/hermes-agent),
adaptada para estaciones de trabajo Windows que permanecen encendidas.** Reúne
CLI, Electron Desktop, Gateway de mensajería, perfiles, inferencia local,
memoria semántica y automatización en un solo árbol de código y un mismo core.

Mantenida independientemente en
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows).
No está afiliada ni respaldada por Nous Research. Se conservan la atribución
upstream y la [licencia MIT](LICENSE).

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

**Versión del código fuente: 0.24.0** (`2026.11.22`) · canales: `stable`, `preview`

## Funciones principales

| Superficie | Uso |
| --- | --- |
| CLI | Chat interactivo, configuración, herramientas, habilidades y diagnóstico |
| Electron Desktop | Chat nativo, perfiles, Security Center, Bot Mode y paneles Git |
| Gateway | Mensajería de larga duración en Telegram, Discord, Slack, LINE, Signal y más |
| TUI | Interfaz de terminal Ink mediante stdio JSON-RPC |
| Inferencia local | llama.cpp/GGUF junto a proveedores remotos |
| Automatización | Cron, habilidades, MCP, delegación y kanban |

Las capacidades opcionales viven en los bordes (plugins, habilidades y MCP), no
en un conjunto de herramientas cada vez mayor que se envía con cada llamada al
modelo.

## Nuevo: búsquedas web con RustXNG

El plugin incluido `web-rustxng` puede conectar la herramienta existente
`web_search` de Hermes con un servicio de metabúsqueda RustXNG alojado por el
operador. Hermes usa la búsqueda web para información actual; también se puede
añadir una instrucción al prompt del perfil para verificar fuentes con mayor
frecuencia. No busca automáticamente en cada mensaje. RustXNG solo busca; la
extracción del contenido de una página requiere otro proveedor.

Para una instalación desde código fuente:

```powershell
git submodule update --init plugins/rustxng
cargo build --manifest-path plugins/rustxng/Cargo.toml --locked --release
.\plugins\rustxng\target\release\rustxng.exe --profile standard --bind 127.0.0.1 --port 8888
```

En el entorno que inicia Hermes, configura
`RUSTXNG_URL=http://127.0.0.1:8888` y selecciona el backend en el perfil activo:

```powershell
uv run hermes config set web.search_backend rustxng
```

Consulta la [guía de integración de RustXNG](plugins/web/rustxng/README.md) para
los pasos completos, una prueba de búsqueda y la directiva de prompt. Usa el
perfil `standard` como punto de partida. RustXNG envía las consultas a los
proveedores habilitados en ese perfil: no incluyas secretos ni texto privado de
conversaciones. Mantén el servicio enlazado a `127.0.0.1` salvo que hayas
diseñado y protegido una instalación de red. Revisa las condiciones de cada
fuente antes de habilitar otros perfiles; el uso personal no las anula.

## Instalación rápida

Requisitos: Windows 11 x64, PowerShell, Git, [`uv`](https://docs.astral.sh/uv/)
y Python 3.11–3.13. Node.js solo es necesario para compilar Desktop desde el
código fuente.

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

| Objetivo | Recurso |
| --- | --- |
| Abrir Desktop desde este checkout | `uv run hermes desktop` |
| Instalador o ZIP portable | [Releases](https://github.com/zapabob/hermes-agent-windows/releases), tras verificar `SHA256SUMS.txt` |
| Guía de instalación de Windows | [`docs/windows/INSTALL.md`](docs/windows/INSTALL.md) |
| Integraciones opcionales | [`docs/windows/INTEGRATIONS.md`](docs/windows/INTEGRATIONS.md) |

Un push a `main` no demuestra que se haya publicado un instalador estable. Los
secretos pertenecen al perfil activo; no subas tokens, bases de datos ni pesos
de modelos.

## Límites y seguridad

- El Desktop tiene un único propietario del ciclo de vida de su backend.
- Los cambios destructivos necesitan confirmación y una vía de recuperación.
- Mantén aislados los perfiles, credenciales, sesiones y el estado del Gateway.
- Trata los resultados de búsqueda como contenido externo no confiable.
- Hermes Agent procede de Nous Research; este downstream se mantiene aquí y no
  comparte sus publicaciones, soporte ni certificaciones.

## Documentación

- [README canónico en inglés](README.md) · [guía en japonés](README.ja.md) ·
  [guía en chino simplificado](README.zh-CN.md) · [guía en urdu](README.ur-pk.md)
- [Instalación Windows](docs/windows/INSTALL.md) ·
  [RustXNG](plugins/web/rustxng/README.md) · [Seguridad](SECURITY.md)
- [Política downstream](DOWNSTREAM_POLICY.md) ·
  [Registro de funciones](FEATURES.yaml) · [cambios mantenidos](CARRY.yaml)

## Licencia y atribución

Hermes Agent es desarrollado por Nous Research bajo la licencia MIT. Este
downstream conserva la atribución y el historial de contribuciones, y se
distribuye bajo la misma [licencia MIT](LICENSE).
