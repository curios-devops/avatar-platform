# CLAUDE.md — avatar-platform

## GPU en la nube (RunPod): regla de apagado (Marcelo, 2026-11-12)
- **Trabajo de Claude:** toda GPU que enciendas para un trabajo se apaga (terminate) en cuanto el trabajo termina.
- **Pruebas de Marcelo:** si Marcelo necesita probar, la GPU queda encendida **máximo 1 hora** desde que está lista para él, salvo que él indique otra duración.
  Avísale la hora exacta de apagado. Espera el resultado de su prueba y confirma el apagado; si no responde, apágala igual al cumplirse la hora.
- **Siempre, sin excepción:** vigilante en el Mac que sobreviva a cortes de red (`.triage/decide/livetalking/pod.py watchdog`, con `MAX_MINUTES`), apagado propio dentro del pod (`MAX_SECONDS` en `boot.sh`) y `caffeinate` mientras dure.
- **Al terminar y al empezar cada sesión:** verifica en la API que hay 0 pods y 0 USD/h, y dilo con el saldo.
- Tope por sesión: 1 USD salvo que Marcelo diga otro. El 2026-11-11 un vigilante caído dejó un pod toda la noche (3,28 USD).
