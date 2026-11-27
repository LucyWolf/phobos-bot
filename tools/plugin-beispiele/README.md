# Plugin-Beispiele · Plugin examples

Fertige Plugins zum Abschreiben. Lade eine Datei unter **Einstellungen → Plugins** hoch (oder
per Link), dann aktivierst du sie je Server. Die ausführliche Beschreibung des Formats steht in
der [Haupt-README](../../README.md#plugins).

Ready-made plugins to copy. Upload a file under **Settings → Plugins** (or by link), then turn
it on per server. The full format reference is in the [main README](../../README.md#plugins).

| Datei · File | Was es zeigt · What it shows |
|---|---|
| [`plugin-beispiel.json`](plugin-beispiel.json) | Ein komplettes Plugin: Ticket-Panel, Befehle, Level-Belohnung, Wortliste — **und** ein Datenpunkt-Teil (`daten`). Der übliche Startpunkt. |
| [`plugin-beispiel-datenpunkte.json`](plugin-beispiel-datenpunkte.json) | Legt nichts an, **liest nur** die VRC-Link-Datenpunkte und stellt sie unter einer Adresse bereit. |
| [`plugin-beispiel-welt.json`](plugin-beispiel-welt.json) | Mehrere Quellen zusammen (`profile`, `level`, `vrchat`) für eine VRChat-Welt. |

## Datenpunkte — Beispiel mit „Max Mustermann"

Ein Plugin nennt im Abschnitt `daten` nur, **welche** Felder es lesen will. Die echten Werte
kommen von den bestätigten VRC-Link-Verknüpfungen deines Servers. Hat sich **Max Mustermann**
verknüpft (bestätigt, „trusted", 18+, Supporter), liefert die Abruf-Adresse:

```json
{
  "gefunden": true,
  "plugin": "beispiel-datenpunkte",
  "daten": {
    "vrchat": [
      { "vrchat_name": "Max Mustermann", "trust": "trusted", "verifiziert_18": true, "supporter": true, "gruppenmitglied": false }
    ]
  }
}
```

Enthalten ist **nur**, was Phobos freigibt — der VRChat-Name und die vier Felder. Keine
Discord-ID, keine E-Mail, kein Token. Wer nicht bestätigt ist, steht gar nicht drin.

The `daten` section only declares **which** fields a plugin may read; the real values come from
your server's confirmed VRC-Link entries. Only what Phobos releases is included — the VRChat
name and the four fields, nothing else.

## Debug: prüfen, bevor du baust

Jeder Server hat im **VRC-Link**-Reiter oben ein 🐞-Icon → eine kleine Konsole (keine Shell,
nur feste Befehle):

- `data <name>` — genau die Datenpunkte, die ein Plugin bekäme (z. B. `data Max`).
- `status <name>` — der volle Verknüpfungs-Status, auch wartende — um zu sehen, warum bei
  jemandem Daten fehlen (noch `pending`, kein Eigentumsnachweis …).
- `live` — die VRC-Link-Vorgänge dieses Servers in Echtzeit, bis `stop`.

So siehst du **vor** dem Bauen, welche Felder es gibt und was real drinsteht — statt zu raten.

Every server has a 🐞 icon at the top of its **VRC-Link** tab → a small console (not a shell,
fixed commands only): `data <name>`, `status <name>`, and `live` (stream until `stop`). Use it
to see the real values before you build a plugin.
