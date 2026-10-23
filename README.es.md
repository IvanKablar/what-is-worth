# What is Worth?

[English](README.md) · [Deutsch](README.de.md) · **Español** · [中文](README.zh.md) · [日本語](README.ja.md) · [Русский](README.ru.md)

What is Worth? muestra cuánto valor de API consumen tus agentes de programación con IA. El centro no es el mes natural, sino el periodo de la suscripción, de un reinicio semanal al siguiente. Para cada cuenta mide además cuántos dólares vale un punto porcentual de la cuota semanal.

Los costes se calculan siempre a partir de tokens: los tokens de cada respuesta de la API, valorados a precio de lista de la API. El porcentaje de uso que informa Claude Code solo sirve para comparar ese valor con la suscripción.

Hoy se admite Claude Code. Otros agentes se pueden añadir como adaptadores. Todo funciona en local: sin cuenta, sin proxy y sin enviar datos. La única conexión de red descarga una vez al día la lista de precios de LiteLLM.

## Funciones

- **Resumen desde el reinicio semanal** de la cuenta con sesión iniciada: uso, valor API, valor por punto porcentual, ritmo y cuándo se alcanzará el límite.
- **Desglose** por día, modelo y proyecto. Un proyecto es un repositorio git. Los worktrees y subdirectorios cuentan para su repositorio principal. Los proyectos abarcan todas las cuentas del periodo.
- **Todas las cuentas en una tabla**, cada una en su propio periodo semanal con su propia hora de reinicio.
- **Precio del plan frente al valor API:** el precio de lista de cada plan por semana y un factor: valor API por punto porcentual dividido entre lo que cuesta un punto porcentual en el plan.
- **Totales de todas las cuentas:** hoy, esta semana, este mes y en total.
- **Semanas anteriores** según el calendario de reinicios de la cuenta.
- **Línea de estado de Claude Code** con uso semanal, coste desde el reinicio, valor por punto porcentual, cuenta atrás y coste de la sesión y de la última consulta.
- **Informes** por día, semana y mes sobre todo el historial.
- **Seis idiomas:** alemán, inglés, español, chino, japonés y ruso.

Ejemplo de línea de estado:

```
Semana 51 % · 8,04 US$ desde el reinicio · Reinicio lun 01:00 (faltan 3 d 7 h) · Sesión 24,12 US$ · Consulta 2,34 US$
```

## Requisitos

- Python 3.11 o superior. No hacen falta más paquetes.
- Git, para detectar proyectos y publicar versiones.
- Claude Code, que guarda sus transcripciones en `~/.claude/projects/`.

## Instalación

1. Clonar el repositorio, por ejemplo en `~/what-is-worth`.
2. Crear una versión publicada. Exporta el último commit a `~/.local/share/what-is-worth/app`:

   ```
   scripts/release.sh
   ```

3. Poner `wiw` en la ruta:

   ```
   ln -s ~/.local/share/what-is-worth/app/bin/wiw ~/.local/bin/wiw
   ```

4. Añadir la línea de estado a `~/.claude/settings.json`:

   ```json
   "statusLine": {
     "type": "command",
     "command": "/home/<usuario>/.local/share/what-is-worth/app/bin/wiw statusline",
     "padding": 0
   }
   ```

5. Leer todo una vez. Unas 2.700 transcripciones tardan entre 10 y 20 segundos:

   ```
   wiw sync
   ```

Por defecto, Claude Code borra las transcripciones a los 30 días. Para conservar el historial, pon un valor alto en `cleanupPeriodDays` dentro de `~/.claude/settings.json`. Los datos ya leídos permanecen en el registro aunque su transcripción se borre después.

## Uso

| Comando | Efecto |
|---|---|
| `wiw` | resumen desde el último reinicio semanal, igual que `wiw overview` |
| `wiw overview --weeks 10` | resumen con diez semanas anteriores |
| `wiw report day` | coste por día, también `week` y `month`, opcionalmente con `--since 2026-09-01` |
| `wiw report project` | coste por proyecto en todo el historial, opcionalmente con `--since` |
| `wiw sync` | leer datos nuevos; si no, ocurre automáticamente |
| `wiw sync --rebuild` | volver a leer las transcripciones existentes, por ejemplo tras cambiar las reglas de lectura |
| `wiw reprice` | recalcular todos los costes con la lista de precios actual |

Dentro de Claude Code, abre el resumen con `! wiw`. No interviene ningún modelo, así que no gasta tokens.

En cada actualización, la línea de estado lee solo las líneas nuevas de su propia sesión. Como mucho cada cinco minutos lanza además una lectura de todas las transcripciones en segundo plano.

## Configuración

| Variable | Significado | Valor por defecto |
|---|---|---|
| `WIW_LANG` | idioma: `de`, `en`, `es`, `zh`, `ja` o `ru` | idioma del sistema; si no, inglés |
| `WIW_DATA_DIR` | ubicación del registro y de la versión publicada | `~/.local/share/what-is-worth` |
| `WIW_CONFIG_DIR` | ubicación de los precios propios | `~/.config/what-is-worth` |
| `WIW_CACHE_DIR` | caché de la lista de precios | `~/.cache/what-is-worth` |
| `WIW_CLAUDE_DIRS` | directorios de configuración de Claude adicionales, separados por `:` | `~/.claude` y `CLAUDE_CONFIG_DIR` |

Los precios propios, por ejemplo para un modelo que LiteLLM aún no conoce, van en `~/.config/what-is-worth/prices.json`. Las claves son las de LiteLLM y los precios son por token:

```json
{
  "claude-modelo-nuevo": {
    "input_cost_per_token": 0.000004,
    "output_cost_per_token": 0.00002,
    "cache_read_input_token_cost": 0.0000002,
    "cache_creation_input_token_cost": 0.000005,
    "cache_creation_input_token_cost_above_1hr": 0.000008
  }
}
```

Después, ejecuta `wiw reprice`.

Las carpetas que git ya no puede resolver, como worktrees borrados, se pueden asignar a un proyecto en `~/.config/what-is-worth/projects.json`. Las claves son patrones glob para la carpeta, y también cubren sus subdirectorios:

```json
{
  "~/code/my-app-*": "my-app"
}
```

Las reglas se aplican de inmediato a todo el historial. Solo actúan cuando git no puede asignar la carpeta. Casi solo hacen falta para el periodo anterior a la instalación: desde entonces What is Worth? guarda la asignación mientras el worktree todavía existe.

## Cómo se calcula

**Fuente de datos.** Claude Code escribe cada respuesta de la API con sus tokens en una transcripción por sesión, y los subagentes y flujos de trabajo en archivos propios. A menudo una respuesta aparece varias veces. What is Worth? conserva por cada id de mensaje la copia transmitida por completo y prefiere la conversación principal a las repeticiones en subagentes.

**Precios.** Las tarifas vienen de LiteLLM. Incluyen entrada, salida, lectura de caché y las dos duraciones de caché de cinco minutos y una hora. Se añaden el precio doble del modo rápido, un recargo del 10 % por residencia de datos, las búsquedas web a 10 $ cada 1.000 y las tarifas de contexto largo. Si un prompt supera el umbral, por ejemplo más de 100.000 tokens en Haiku 5.5, toda la solicitud paga la tarifa más alta, no solo el exceso.

**Periodos de suscripción y cuentas.** Solo la línea de estado conoce el uso, la hora de reinicio y la cuenta con sesión iniciada. Los registra en cada actualización. Cada respuesta pertenece a la cuenta que tenía la sesión iniciada en ese momento. Un `/login` afecta a todas las sesiones en curso a la vez.

**Valor por punto porcentual.** El coste de una cuenta desde la primera lectura de uso del periodo, dividido entre el aumento del uso desde entonces. Claude Code solo informa porcentajes enteros, por eso el valor aparece a partir de un aumento de 5 puntos, lo que mantiene el error de redondeo por debajo de un 20 %.

**Coste de una consulta.** Todas las respuestas de una sesión desde una entrada hasta la siguiente, subagentes incluidos.

## Precisión

- **Frente a ccusage:** de agosto a octubre de 2026, tokens y costes coincidieron por mes y modelo. Desde entonces What is Worth? corrige dos errores de conteo que ccusage aún tiene, que afectan a un 0,01 % del coste.
- **Tarifas:** todos los modelos usados se contrastaron con la página oficial de precios de Anthropic. La tabla está en `scripts/official_prices.json`.
- **Comprobación independiente:** `scripts/verify_projects.py` recalcula todas las transcripciones sin el código del programa y compara por proyecto con el registro. Opcionalmente añade una exportación de ccusage:

  ```
  npx ccusage@latest claude session --json --offline > /tmp/cc.json
  python3 scripts/verify_projects.py /tmp/cc.json
  ```

- **Frente al contador de Claude Code:** la suma por sesión es un 1 % menor, porque Claude Code no escribe algunas llamadas en segundo plano en la transcripción.

Los precios de los planes son precios de lista sin impuestos de claude.com/pricing: Pro 20 $, Max 5x 100 $, Max 20x 200 $ al mes. La página solo indica Max «desde 100 $», así que el precio de Max 20x es el conocido hasta ahora. Los precios reales pueden variar por moneda, impuestos, pago anual y descuentos.

Todos los importes son equivalentes de API a precio de lista. Con una suscripción Pro o Max son valores de referencia, no una factura.

## Limitaciones conocidas

- **Cuentas solo desde la instalación.** Las transcripciones no contienen la cuenta. Los costes anteriores a la primera actualización de la línea de estado aparecen como «no atribuibles».
- **Cambios de cuenta sin línea de estado.** Si tras un inicio de sesión solo usas `claude -p` o el IDE, el cambio se detecta en la siguiente actualización de una línea de estado en terminal.
- **Primeros intentos rechazados.** Cuando un modelo rechaza antes de producir salida y responde otro, la alternativa se valora correctamente. Si el intento rechazado cuesta algo depende de su categoría, que no figura en la transcripción, así que no se cuenta.
- **Worktrees borrados.** Los worktrees borrados antes de su primera lectura no se pueden asignar a un repositorio y aparecen con el nombre de su carpeta. Una regla en `projects.json` puede asignarlos. Los subdirectorios borrados de un repositorio conocido siguen contando para él.
- **Un solo equipo.** Cada equipo lleva su propio registro.

## Estructura

```
src/whatisworth/
  model.py                 registros comunes a todas las fuentes: respuesta, consulta, límite, cuenta
  sources/base.py          interfaz para fuentes
  sources/claude_code.py   adaptador de Claude Code
  ledger.py                registro SQLite
  ingest.py                lectura incremental con bloqueo
  pricing.py               precios de LiteLLM con valores propios
  projects.py              directorio de trabajo → repositorio git
  insights.py              periodos, cuentas, sumas, valor por punto porcentual
  statusline.py            línea de estado
  cli.py                   comandos
  i18n.py, format.py, locales/   idiomas y formatos
```

El registro guarda tokens y hechos en bruto. Los costes se calculan al leer y se pueden recalcular con `wiw reprice`. Proyectos y cuentas se asignan solo al evaluar. Una fuente nueva, como Gemini, es un adaptador más que produce los mismos registros.

## Desarrollo

```
python3 -m pytest -q tests
bin/wiw            # ejecutar la copia de trabajo
scripts/release.sh # publicar el último commit
```

La línea de estado y `wiw` solo se ejecutan desde la versión publicada, así que los cambios a medias de la copia de trabajo nunca se ejecutan en vivo. Ejecuta `scripts/release.sh` después de cada commit que deba publicarse.

Los textos nuevos van en todos los archivos de `src/whatisworth/locales/`. Una prueba comprueba que todos los idiomas tengan las mismas claves y marcadores.

## Previsto

- Gemini CLI como segunda fuente, leída del registro de telemetría OTel en lugar de los archivos de chat. Solo el registro incluye también las llamadas del enrutador y del resumidor.
- Un panel en el navegador sobre la misma evaluación.
- Reglas de proyecto para carpetas que no se pueden asignar automáticamente.
