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

## 1.19.28 — `beta` — 16.11.2026

**VRC-Link: Freigabe im Kanal** (alles einzeln abschaltbar, Standard aus)
- Neu: **18+ bei VRChat verlangen.** Ohne bestätigtes 18+ wird niemand automatisch
  freigegeben — die Anfrage bleibt liegen, abgelehnt wird dabei niemand. „Nicht bestätigt"
  heißt auch „VRChat sagt gerade nichts dazu".
- Neu: **18+-Spalte** in der Verknüpfungsliste — vor der Freigabe sichtbar, nicht erst
  danach.
- Neu: **Wartende Verknüpfungen im Kanal melden.** Einbettung mit Discord-Name,
  VRChat-Name, 18+-Status, Trust-Rang und Profillink, darunter ✅ Annehmen und ❌ Ablehnen.
  Ablehnen fragt nach einem Grund (freiwillig).
- Entscheiden darf, wer eine einstellbare Rolle hat; ohne Auswahl gilt „Server verwalten".
- Annehmen gibt Discord-Rolle und Spitzname, die VRChat-Gruppenrollen und die Einladung —
  derselbe Weg wie im Dashboard. Ablehnen löscht die Verknüpfung, damit der Name für einen
  neuen Versuch frei ist.
- Neu: **Entscheidung per DM** an den Betroffenen, bei Ablehnung mit Grund.
- Neue Log-Kategorie **VRC-Link** für den Log-Kanal.
- Die Meldung wird nach der Entscheidung umgeschrieben (wer, wann, warum) und verliert
  ihre Knöpfe — auch dann, wenn im Dashboard entschieden wurde.

---

## 1.19.27 — `beta` — 16.11.2026

**VRC-Link**
- Neu: **Suche** über der Verknüpfungsliste. Gesucht wird im Discord-Namen, im
  VRChat-Namen und in beiden Kennungen — wer eine Nummer aus dem Protokoll hat, kann sie
  einsetzen.
- Neu: **10, 20 oder 50 Einträge je Seite**, selbst einstellbar, mit Blättern darunter.
  Suche und Seitengröße wandern beim Umblättern mit.
- Die Zahl oben zählt weiter alle Verknüpfungen, auch während einer Suche; daneben steht
  dann, wie viele davon passen.

---

## 1.19.26 — `beta` — 16.11.2026

**Sicherheit**
- Behoben: Der Server ließ sich dazu bringen, **Adressen im eigenen Netz abzurufen**. Beim
  Holen eines Umfragebildes (eigene Bildbreite) wurde die Adresse gar nicht geprüft, und
  beim Suchen eines Vorschaubildes nur die erste — eine fremde Seite konnte per Umleitung
  auf `http://127.0.0.1:…` zeigen. Umleitungen werden jetzt selbst aufgelöst und vor jedem
  Schritt geprüft.
- Behoben: Das **AMP-Passwort folgte einer geänderten Adresse**. Ein leeres Passwortfeld
  heißt „behalten" — damit reichte es, die Adresse auf einen eigenen Server zu ändern und
  zu speichern, um die Zugangsdaten dorthin zu schicken. Wer den Host wechselt, muss das
  Passwort jetzt neu eingeben.

Beides gemeldet aus einer fremden Installation und hier mit echten lokalen Servern
nachgestellt.

---

## 1.19.25 — `beta` — 16.11.2026

**VRChat**
- Behoben, dringend: Ein **zweites VRChat-Konto verschwand beim nächsten Neustart**. In der
  Migrationsliste von `init_db()` — die bei jedem Start durchläuft — standen noch zwei
  Anweisungen aus der Zeit, als es nur ein Konto gab: sie zogen eine Zeile auf das
  Standardkonto um und löschten alle übrigen. Seit mehrere Konten möglich sind, räumte das
  bei jedem Start auf, ohne Meldung und ohne Spur. Gemeldet aus einer fremden Installation,
  hier nachgestellt und per Test abgesichert.

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
