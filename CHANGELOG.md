# Änderungen

Was sich mit jeder Version geändert hat — **jede** Version, auch die, die nur auf `beta`
stand. Der Sinn dieser Datei ist das spätere Nachvollziehen: wer wissen will, wann ein
Verhalten dazugekommen oder wieder verschwunden ist, soll das hier finden und nicht in
hundert Commit-Nachrichten suchen müssen.

Neueste Version oben. Jede Version bekommt einen Abschnitt mit Datum und dem Zweig, auf
dem sie zuerst stand (`beta` oder `main`). Geschrieben wird in derselben Änderung, die
auch die Versionsnummer hochsetzt — nicht nachträglich.

Was davor war, steht in der Commit-Geschichte: `git log --oneline` oder auf GitHub unter
*Commits*. Diese Datei fängt am 09.11.2026 an.

---

## 1.19.24 — `beta` — 11.11.2026

**Einrichtung**
- Neu: Oben im Fenster steht ein Knopf **„Einrichtung beenden"**. Damit kommt man ins
  Dashboard, auch wenn noch Pflichtschritte offen sind — den Rest holt man später über
  den Eintrag „Einrichtung" in der Seitenleiste nach.
- Den Knopf gibt es erst, wenn das eigene Konto eingerichtet ist (Schritt 1). Solange
  noch `admin`/`admin` gilt, führt jeder Ausgang auf ein Dashboard, in das jeder
  hineinkommt, der dieses Projekt kennt — das ist das Einzige, was sich nicht nachholen
  lässt.

---

## 1.19.23 — `main` — 09.11.2026

Stand, mit dem diese Datei beginnt. Alles Ältere siehe Commit-Geschichte.

**VRChat**
- Neu: Wer Discord verlässt — auch durch Kick oder Bann —, kann auch aus der
  VRChat-Gruppe entfernt werden. Haken je Server im VRC-Link-Reiter, standardmäßig aus.
  Die Verknüpfung wird dabei gelöscht: wer zurückkommt, muss sich neu verknüpfen und
  prüfen lassen, bevor er wieder eine Einladung bekommt.
- Neu: Der erklärende Text des Verknüpfungs-Panels lässt sich abschalten. Er steckte
  auch in der Begrüßungs-DM; ist er aus und steht kein eigener DM-Text da, bleibt die DM
  ganz aus.
- Behoben: Die Begrüßungs-DM erzeugte den persönlichen Link, bevor feststand, ob
  überhaupt etwas zu schicken ist — dabei entstand ein gültiger Zugangsschlüssel, den
  niemand je bekam.

**Einrichtung**
- Der Assistent erklärt beim Token-Schritt, wo der Token herkommt: fünf Schritte, Link
  ins Discord Developer Portal, und die drei privilegierten Intents gleich mit.
- Behoben: `hidden` wirkte im Dashboard nicht, weil `.btn` und `.nav-item` eigene
  `display`-Regeln setzen. Dadurch stand „Überspringen" auf jeder Seite des Assistenten
  und „Einrichtung" dauerhaft in der Seitenleiste.
