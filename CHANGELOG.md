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

## 1.19.36 — `beta` — 17.11.2026

**Profile: zweiter Durchgang**

*„Hat nichts eingetragen" war nicht wahr*
- Wer keine 18+-Bestätigung hat, sieht nur die Bio. Standen bei jemandem **nur** Felder
  hinter der Altersschranke, antwortete der Bot trotzdem „hat nichts eingetragen" — glatt
  falsch, und der Grund blieb verborgen.
- Jetzt gibt es dafür einen eigenen Satz. Er gilt **beiden** Fällen — wirklich leer und
  nicht sichtbar —, denn sonst verriete schon die Wahl der Antwort, dass da etwas steht.

*Der Freigabe-Knopf konnte doppelt oder gar nicht antworten*
- Umschreiben der Nachricht und Rückmeldung standen in **einem** `try`. Schlug das Senden
  fehl, lief es im `except` noch einmal — die Meldung kam doppelt. Scheiterte schon das
  Umschreiben, war die Interaktion unbeantwortet und die Rückmeldung lief ins Leere.
- Jetzt zwei getrennte Schritte: die Umstellung wird in jedem Fall genau einmal gemeldet.

*Die Welt kennt keine Altersschranke*
- In Discord hängt an kinks/triggers/limits eine 18+-Prüfung. In einer VRChat-Welt gibt es
  so etwas nicht — was dort auf einer Tafel steht, sieht jeder, der davorsteht.
- Die Leseadresse markiert deshalb jedes Feld mit `erwachsen: true/false`, damit die Welt
  selbst entscheiden kann. **Entschieden ist damit nichts** — das muss die Welt tun.

*Aufgeräumt*
- `FeldModal` merkte sich eine Server-Kennung, die es nie benutzt hat.

---

## 1.19.35 — `beta` — 17.11.2026

**Slash-Befehle standen doppelt in der Liste**
- Gemeldet an `/inspect`: zweimal da, und einer antwortete „this command is outdated".
  Es lag nicht am Befehl — es betraf **jeden** geänderten Befehl nach **jedem** Update.
- Ursache: der Bot meldete jeden Befehl **global** an und kopierte ihn **zusätzlich** in
  jeden Server. Sehen beide Fassungen gleich aus, zeigt Discord nur eine. Nach einem Update
  ist die Server-Kopie aber sofort aktuell und die globale noch bis zu einer Stunde alt —
  dann stehen zwei verschiedene da, und die alte lässt sich anklicken, ohne zu funktionieren.
- Jetzt wird die globale Liste beim Start geleert; angemeldet wird nur noch je Server. Die
  Server-Kopie war ohnehin die, die sofort greift — sie war der Grund, warum die Kopien
  damals eingebaut wurden.
- Der Befehlsbaum des Bots behält dabei alle Befehle: ohne sie gäbe es nichts zu kopieren.
  Scheitert der Abgleich mit Discord, werden sie trotzdem zurückgelegt — ein Bot ohne
  Befehle wäre schlimmer als ein doppelter Eintrag.

**Was das für dich heißt**
In **Direktnachrichten** gibt es die Befehle danach nicht mehr. Alle Befehle dieses Projekts
beziehen sich ohnehin auf einen Server. Die doppelten Einträge verschwinden beim nächsten
Start des Bots; bis dahin funktioniert der Eintrag mit den Parametern.

---

## 1.19.34 — `beta` — 17.11.2026

**Das Changelog steht jetzt auf der Updates-Seite**
- Die Seite zeigte bisher nur Commit-Zeilen, die bei GitHub geholt werden. Ohne Netz stand
  dort nichts — also genau dann nichts, wenn man wissen will, was man sich einspielt.
- Neu darunter: **„Was sich mit jeder Version geändert hat"**, aufklappbar, neueste Version
  offen. Gelesen wird `CHANGELOG.md` aus dem Repo, von der Platte. Dazu ein Verweis auf die
  ganze Datei bei GitHub.
- Fremder Text wird dabei nicht zu Markup: erst wird alles entschärft, danach kommen genau
  drei Dinge zurück — **fett**, `Code` und Aufzählungen. Kein Markdown-Paket dafür, das wäre
  eine Abhängigkeit mehr für drei Muster und eine Stelle mehr, an der Text zu HTML wird.

**Wie die Notizen ab jetzt geschrieben sind**
Gegliedert statt als Absatzblock, das Schwerste zuerst, und sie erklären **warum** statt
**was** — was im Diff steht, gehört nicht in die Notiz. Dazu, wo es nötig ist: was man selbst
tun muss, und was nicht geprüft werden konnte. Das gilt für diese Datei **und** für die
Commit-Nachrichten, denn die Updates-Seite baut ihre Liste aus den Commits.

---

## 1.19.33 — `beta` — 17.11.2026

**Profile: Fehlersuche an der neuen Funktion**
Sechs Punkte, alle gefunden bevor jemand sie benutzt hat:
- **Der Freigabe-Knopf schaltete nicht zurück.** Er merkte sich den Zustand aus dem Moment,
  in dem die Nachricht entstand — beim zweiten Druck schrieb er denselben Wert noch einmal
  und behauptete trotzdem, ausgeschaltet zu haben. Bei einer Freigabe für kinks/limits war
  das der gefährlichste Fehler, den diese Funktion haben konnte. Der Zustand wird jetzt beim
  Drücken frisch gelesen, die Beschriftung ändert sich mit.
- **Zwei Server mit demselben Schlüssel hätten sich gegenseitig gelesen.** Gesucht wird über
  den Schlüssel, nicht über den Server — ein zweiter Server mit derselben Zeichenkette hätte
  die Profile des ersten ausgeliefert. Wird beim Speichern abgelehnt.
- **Ein Schlüssel wie „test" war erlaubt.** Jetzt mindestens 20 Zeichen, sobald die Anzeige
  in der Welt eingeschaltet wird.
- **Die beiden neuen Rollenfelder liefen an der Rollenprüfung vorbei**, die alle anderen
  durchlaufen. Nachgetragen.
- **Die Leseadresse hatte keine Bremse.** 60 Anfragen je Minute und Absender; darüber 429.
- **Die Antwort spiegelte die Eingabe zurück** (`vrchat_name`). Jetzt kommt der gespeicherte
  Name aus der Verknüpfung.
- Dazu: die Befehle gelten nur noch auf Servern, nicht in Direktnachrichten — dort gibt es
  weder Rollen noch einen Server, auf den sich ein Profil beziehen könnte.

---

## 1.19.32 — `beta` — 17.11.2026

**Profile (neu, erste Fassung, Standard aus)**
Angaben, die Mitglieder selbst über sich hinterlegen — gewünscht für die Anzeige in einer
VRChat-Welt.
- Befehle `/bio`, `/kinks`, `/triggers`, `/limits` (Eingabefenster mit dem bisherigen Text
  darin), `/profil` fürs eigene, `/inspect @person` für fremde, `/profil-loeschen`.
- Jede Antwort des Bots ist nur für die fragende Person sichtbar. Ein Profil landet nie
  in einem Kanal.
- **18+ ist Pflicht** für kinks/triggers/limits, nicht für die Bio. Als Nachweis zählt die
  VRChat-Altersbestätigung aus dem VRC-Link oder eine Rolle, die der Server dafür bestimmt.
  Wer keinen Nachweis hat, sieht diese Felder auch bei anderen nicht — darf aber nachsehen
  und sein eigenes Profil öffnen.
- Im Dashboard ein eigener Reiter: an/aus, Rolle als 18+-Nachweis, wer `/inspect` benutzen
  darf.

**Anzeige in der VRChat-Welt — ohne Pastebin**
- Gewünscht war, die Texte nach Pastebin/Gist zu schieben. Das wäre eine öffentliche
  Adresse für sehr private Angaben, bei einem Dienst, der nichts davon wieder loswird.
  Stattdessen liefert Phobos sie selbst: `GET /api/profil?key=…&vrc=NAME`.
- Drei Schranken, die eine Pastebin-Adresse nicht hätte: die Anzeige muss eingeschaltet
  sein, die Anfrage braucht den Schlüssel des Servers, und **die betroffene Person muss ihr
  Profil selbst freigegeben haben**. Ohne Freigabe sieht die Welt nichts, auch mit
  Schlüssel. Gelöscht ist wirklich gelöscht.
- Gesucht wird über den VRChat-Namen aus dem VRC-Link — das ist das Einzige, was eine Welt
  über ihr Gegenüber weiß.

---

## 1.19.31 — `beta` — 17.11.2026

**Tickets: die Grenze zählt je Kategorie**
- Gemeldet an einem Panel mit fünf Kategorien: wer ein Verification-Ticket offen hatte,
  konnte keinen Regelverstoß mehr melden. Die Prüfung hing am **Panel** und sah die
  gewählte Kategorie gar nicht an — ein offenes Ticket sperrte alles andere mit, obwohl
  das verschiedene Anliegen sind, die oft verschiedene Leute bearbeiten.
- Ein Ticket merkt sich jetzt seine Kategorie (`tickets.option_id`), und die Grenze gilt
  je Kategorie. Panels mit einfachem Knopf verhalten sich unverändert.
- Wer es streng will, setzt im Panel den Haken **„Nur ein Ticket gleichzeitig"** und
  bekommt das alte Verhalten zurück.
- Eigene Antwort für den Fall „in dieser Kategorie hast du schon eins" — der alte Satz
  klang falsch, wenn daneben andere Tickets offen stehen dürfen.

---

## 1.19.30 — `beta` — 17.11.2026

**Das Startskript fasst keine fremden Dateien mehr an**
- Auf einem Server mit mehreren Instanzen liegen die Datenordner der *anderen*
  Installationen im selben Verzeichnis wie das Repo (`data-zerafi/`, `data-paniczone/`).
  Der Rundumschlag über `/repo` aus 1.19.29 hat sie beim ersten Start mit umgeschrieben —
  15 Einträge, die diesen Bot nichts angehen. Kaputt ging dabei nichts (jene Container
  laufen als root und kommen an Dateien von 1000 trotzdem heran), passieren durfte es
  trotzdem nicht.
- Angefasst wird jetzt nur noch, was der Bot wirklich braucht: `.git`, das Repo-Verzeichnis
  selbst und die obersten Einträge, **die git kennt**. Was git nicht kennt, bleibt liegen.

---

## 1.19.29 — `beta` — 16.11.2026

**Der Bot läuft nicht mehr als root**
- Bis hierher lief `python main.py` im Container als uid 0 — nie Absicht, sondern der
  Docker-Standard, weil das Dockerfile nie eine `USER`-Zeile hatte. Ein Einstieg war das
  nicht (kein Docker-Socket, siehe `10cb891`), aber es machte jeden denkbaren Fehler
  schlimmer: geschrieben worden wäre als root, in das eingehängte Repo — also in den
  Code, der beim nächsten Start läuft.
- Der Container startet jetzt als Benutzer `1000`, gibt **alle** Linux-Fähigkeiten ab
  (`cap_drop: ALL`, nur das Startskript bekommt kurz die fünf, die es zum Umschreiben
  der Besitzrechte braucht) und kann sich keine zurückholen (`no-new-privileges`).
  Der laufende Prozess hat am Ende `CapEff: 0000000000000000`.
- **Einzustellen ist dafür nichts** — kein `user:` in der compose-Datei, keine Nummern.
  Wessen Dateien auf dem Wirt einer anderen Nummer gehören, setzt `PUID`/`PGID`.

**Damit nichts stehenbleibt**
- Bei jeder bestehenden Installation gehören `data/` und das Repo root. Das neue
  `app/entrypoint.sh` rückt die Besitzrechte bei **jedem** Start zurecht, bevor es die
  Rechte abgibt — angefasst wird dabei nur, was tatsächlich falsch steht. Nötig bei jedem
  Start, weil auf dem Server per SSH als root im Repo gearbeitet wird.
- Vor dem Abgeben wird geprüft, ob es überhaupt gutgeht: ob der Rechtewechsel möglich ist
  und ob das Datenverzeichnis als dieser Benutzer beschreibbar ist. Klappt eines davon
  nicht (NFS, Docker Desktop, exFAT, fehlende Fähigkeit), **läuft der Bot wie bisher als
  root weiter** und schreibt den Grund samt Abhilfe ins Container-Protokoll. Ein Container
  in der Neustartschleife wäre schlimmer als ein Bot mit zu vielen Rechten.
- `PHOBOS_ROOT=1` erzwingt das alte Verhalten, falls doch irgendwo etwas klemmt.
- `git config` jetzt `--system` statt `--global`: sonst meldet git im `/repo` als anderer
  Benutzer „dubious ownership" und das Update über das Dashboard wäre tot.

**Wirksam erst beim Neubauen** (`docker compose up -d --build`). Ein Update über das
Dashboard holt nur neuen Code und startet den Prozess neu, es baut das Image nicht neu —
eine laufende Installation ändert sich also erst, wenn sie selbst neu gebaut wird.

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
