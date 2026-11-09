# GTA San Andreas (R36S) – Inside Track betting fix

[Español](#español) · [English](#english)

---

## Español

En el port de **GTA San Andreas** que circula para la **R36S** (y otras consolas con ArkOS), las apuestas de caballos de **Inside Track** no funcionan: entras en la máquina, pero no puedes elegir la cantidad ni empezar la carrera. Este parche lo arregla.

### ¿Es mi versión?

El parche solo funciona con este ejecutable concreto (el que muestra `=== GTA SA ARKOS FIX v9 ===` en `gtasa.log`):

```
gtasa  sha256 3c7bcbda70b46603556f82e77a7a8e7d69e764e51aa53e9083ba0b41a5914415
```

El script lo comprueba solo: si tu `gtasa` es otro, no toca nada.

### Instalación

Necesitas Python 3 (en el PC o en la consola).

1. Haz una copia de tu partida guardada, por si acaso.
2. Descarga `patch_itb.py`.
3. Ejecútalo pasándole la carpeta donde está el ejecutable `gtasa`:

   **Windows** (con la tarjeta SD en el PC, cambia la letra de unidad):
   ```
   python patch_itb.py G:\ports\gtasa
   ```
   **Linux / en la consola por SSH:**
   ```
   python3 patch_itb.py /roms/ports/gtasa
   ```

El script guarda el original como `gtasa.orig` y parchea `gtasa`. Para deshacerlo:

```
python3 patch_itb.py /roms/ports/gtasa --undo
```

### Controles en la pantalla de apuestas

Nombres de los botones de la R36S (A derecha, B abajo, X arriba, Y izquierda):

| Botón | Acción |
|---|---|
| Cruceta ↑ / ↓ | Elegir caballo |
| L1 / R1 | Botones de cantidad, fila 1 |
| L2 / R2 | Botones de cantidad, fila 2 |
| Cruceta ← / → | Botones de cantidad, fila 3 |
| Y / B | Botones de cantidad, fila 4 |
| **A** | **Apostar (empieza la carrera)** |
| X | Salir |

La carrera solo arranca si la apuesta es mayor que 0 $.

### Estado

Probado en:

| Consola | Placa | Firmware |
|---|---|---|
| R36S | HL-R36H-V21 (2024-11-18) | dArkOSen_R36_10152026 |

No está probado en otras consolas ni en otras versiones del port. Si lo pruebas en otra, abre un *issue* y cuéntalo.

---

## English

On the **GTA San Andreas** port that circulates for the **R36S** (and other ArkOS-style handhelds), **Inside Track** horse betting is broken: you can open the betting machine, but you can't pick an amount or start the race. This patch fixes it.

### Is it my version?

The patch only works on this exact executable (the one that prints `=== GTA SA ARKOS FIX v9 ===` in `gtasa.log`):

```
gtasa  sha256 3c7bcbda70b46603556f82e77a7a8e7d69e764e51aa53e9083ba0b41a5914415
```

The script checks this itself and changes nothing if your `gtasa` is different.

### Install

You need Python 3 (on a PC or on the handheld).

1. Back up your save, just in case.
2. Download `patch_itb.py`.
3. Run it on the folder that contains the `gtasa` executable:

   **Windows** (SD card in the PC, adjust the drive letter):
   ```
   python patch_itb.py G:\ports\gtasa
   ```
   **Linux / on the device over SSH:**
   ```
   python3 patch_itb.py /roms/ports/gtasa
   ```

The original is kept as `gtasa.orig`. To undo:

```
python3 patch_itb.py /roms/ports/gtasa --undo
```

### Controls on the betting screen

R36S button labels (A right, B bottom, X top, Y left):

| Button | Action |
|---|---|
| D-pad Up / Down | Pick horse |
| L1 / R1 | Bet amount buttons, row 1 |
| L2 / R2 | Bet amount buttons, row 2 |
| D-pad Left / Right | Bet amount buttons, row 3 |
| Y / B | Bet amount buttons, row 4 |
| **A** | **Place bet (starts the race)** |
| X | Exit |

The race only starts if your bet is above $0.

### Status

Tested on:

| Device | Mainboard | Firmware |
|---|---|---|
| R36S | HL-R36H-V21 (2024-11-18) | dArkOSen_R36_10152026 |

Not tested on other devices or other builds of the port. If you try it elsewhere, please open an issue.

---

## Technical details

The port runs the Android build of the game (`libGTASA.so`) and replaces `CTouchInterface::IsReleased` with its own hook (`gtasa_TouchInterface_IsReleased`) that translates gamepad buttons into touch widgets.

1. **Why betting was broken.** The hook only maps buttons to widgets **by texture name** (`ITB_FIRST_HORSE`, `PLACE_BET`, …). The Inside Track widgets (WidgetIDs 135–149: 5 horses, 8 amount buttons, place bet, exit) have no texture name, so the hook skips all of its betting logic and falls through to the real touch check, which never fires without a touchscreen. The 8 amount buttons (140–147) also have no mapping at all.
2. **The fix.** The `cbz x20` at `0x3b87c` (taken when the name is NULL) now jumps to a small block of new code in the zero padding after `.gcc_except_table` (`0x1a1100`). For IDs 135–149 it reads the port's held-button mask (`0xb0ba78`), detects button releases per widget, and returns `true` for the mapped widget. Every other widget still goes through the original path.
3. **Place bet.** The betting script (`mainV1.scm`) queries widget 148 twice per frame: once inside the amount-button loop (`IS_WIDGET_RELEASED @494`, i = 8) and again in the place-bet check (`IS_WIDGET_RELEASED 148`). A release of 148 is therefore reported to both queries.
4. **ELF.** The RX `PT_LOAD` `filesz`/`memsz` is grown to cover the new code, and the RW `memsz` grows by 0x28 bytes to hold the patch state past the end of `.bss`. 253 bytes change in total.

## Disclaimer

Unofficial and not affiliated with Rockstar Games or the PortMaster project. This repository contains no game files and no port binaries: only the patch script, which you apply to your own copy. Use at your own risk; keep your backup.

## License

MIT – see [LICENSE](LICENSE).
