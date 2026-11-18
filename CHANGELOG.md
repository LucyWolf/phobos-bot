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

## 1.19.44 — `beta` — 18.11.2026

**Reihenfolge ändern durch Ziehen**
- Gewünscht: „nicht nur das verschieben per pfeil sondern links gedrückt halten und
  nachoben ziehen und losslassen". Zeile festhalten, schieben, loslassen — die neue
  Reihenfolge wird sofort gespeichert und die Seite lädt neu.
- **Die Pfeile bleiben.** Ziehen gibt es auf einem Touchgerät nicht und mit der Tastatur
  auch nicht; wer nur die Pfeile hat, soll nicht ausgeschlossen sein.
- Der Mauszeiger wird beim Darüberfahren zur Hand. Ohne das findet die Funktion niemand,
  der nicht danach sucht.

**Zwei Dinge, die dabei schiefgehen können**
- **Die ausgeklappte Bearbeitungszeile wandert mit.** Unter jeder Zeile hängt ihr
  Bearbeiten-Bereich; ohne das stünde er nach dem Ziehen unter einem fremden Eintrag.
- **Ein Klick auf ein Kästchen oder einen Knopf zieht nicht.** Wer etwas ankreuzt, will
  nicht umsortieren.

**Was die Seite schickt, wird nicht geglaubt**
Beim Speichern kommt eine ganze Reihenfolge auf einmal an. Abgeglichen wird sie gegen die
Liste des Servers: fremde und erfundene Nummern fliegen raus, Doppelte zählen einmal, und
was der Browser nicht kannte — im anderen Fenster angelegt — hängt hinten an, statt verloren
zu gehen. Eine leere Liste ändert nichts.

Gespeichert wird als gewöhnliches Formular, danach lädt die Seite neu. Sie zeigt damit, was
in der Datenbank steht, und nicht, was der Browser glaubt — ein fehlgeschlagenes Speichern
fällt sofort auf, statt bis zum nächsten Aufruf hübsch auszusehen.

**Geprüft:** 38 Prüfungen (vorher 23). Neu: die übernommene Reihenfolge, fremde und doppelte
Nummern, eine unvollständige Liste, eine leere Liste, der unberührte Nachbarserver — und
dass die Vorlage alles mitbringt, woran das Ziehen hängt (ziehbare Zeilen, der Aufruf, die
mitwandernde Bearbeitungszeile, der ausgenommene Klick auf Bedienelemente, und dass die
Pfeile noch da sind).

**Nicht geprüft:** das Ziehen selbst — das läuft im Browser.

---

## 1.19.43 — `beta` — 18.11.2026

**Ein Plugin kann jetzt auch Daten lesen**
- Gewünscht: „mach bei den plugins das mann auch andere datenpunkte nehmen kann und
  verwenden also das was der andere tüp wolte kann ein eigenes plugin machen und selber
  einbinden". Das ist die Antwort auf die Anfrage von außen: wer eine eigene Abfrage für
  eine VRChat-Welt braucht, baut sich ein Plugin — statt dass für jeden Sonderfall eine
  neue Schnittstelle in den Bot muss.
- Ein Plugin erklärt unter `daten`, was es lesen möchte. Drei Quellen: **Profile** (nur
  selbst freigegebene), **Level und XP**, **VRChat-Verknüpfungen** — jeweils mit Auswahl
  der Felder.
- Abrufbar unter `/api/plugin/<kennung>?key=…`, **alles in einer Antwort**. Eine Welt lädt
  einmal und sucht selbst darin, statt pro Besucher zu fragen. Bei VRChats Sperrzeit
  zwischen zwei Ladevorgängen ist das der Unterschied zwischen „geht" und „geht nicht".
- Ein Plugin, das nur liest und nichts anlegt, ist jetzt ein gültiges Plugin. Beispiel zum
  Abschreiben: `tools/plugin-beispiel-welt.json`.

**Ein Plugin fragt nur — entschieden wird am Server**
Ein eingespieltes Plugin kommt an gar nichts. Je Ansicht ein Haken und ein eigener
Schlüssel, beides aus, bis jemand es einschaltet. Alle Haken entfernen schaltet den Abruf ab
und löscht den Schlüssel; ein geänderter Schlüssel sperrt die alte Adresse sofort aus. Der
Schlüssel muss mindestens 20 Zeichen haben und darf nicht schon anderswo verwendet werden —
gesucht wird beim Abruf über ihn, ein doppelter zeigte auf den falschen Server.

**Drei Regeln, die nicht einstellbar sind**
1. **Nur freigegebene Profile.** Ein Text erscheint genau dann, wenn die Person selbst den
   Knopf gesetzt hat. Eintragen ist nicht Veröffentlichen.
2. **Keine Discord-Kennungen.** Gefunden wird über den VRChat-Namen aus der Verknüpfung;
   wer keine hat, steht nirgends. Sonst wäre die Antwort eine fertige Liste „VRChat-Name →
   Discord-Konto", und die hat niemand bestellt.
3. **Nur die aufgezählten Quellen und Felder.** Kein Plugin kann eine Tabelle oder Spalte
   nennen, an die niemand gedacht hat — E-Mail-Adressen, Tokens und Verwarnungen sind damit
   nicht „noch nicht freigegeben", sondern unerreichbar. Eine unbekannte Quelle lässt die
   Datei schon beim Hochladen durchfallen, nicht erst im Betrieb.

Dazu dieselbe Bremse je Adresse wie bei der Profil-Schnittstelle: eine Welt fragt alle paar
Minuten, wer dreißigmal in der Minute fragt, probiert Schlüssel durch.

**Geprüft:** 104 Prüfungen (vorher 80). Neu: abgelehnte Quellen und Felder, doppelte
Quellen, leere Feldlisten, ein Plugin das nur liest, eins das gar nichts tut — und an echten
Zeilen: dass ohne Freigabe nichts herauskommt, dass nur das Freigegebene kommt, dass ein
nicht freigegebenes Profilfeld fehlt, dass jemand ohne Verknüpfung nirgends auftaucht, eine
wartende Verknüpfung auch nicht, und dass in **keiner** Zeile eine Discord-Kennung steht.

**Nicht geprüft:** die Oberfläche im Browser und der Abruf aus einer echten Welt.

---

## 1.19.42 — `beta` — 18.11.2026

**Nachfragen kommen jetzt aus der Seite, nicht aus dem Browser**
- Gemeldet: „ich will das es nicht im browser ist sondern bei den bot selber als pop up das
  ist dumm im browser". Das eingebaute `confirm()` stellt jeder Frage „Auf
  &lt;domain&gt; wird Folgendes angezeigt:" voran. Bei einer dynamischen DNS-Adresse liest
  sich die eigene Oberfläche dadurch wie eine Betrugswarnung.
- **49 Stellen** umgestellt, dazu der eine `alert()` auf der Startseite. Ein eigener Dialog
  in der Gestaltung des Dashboards, mit Escape zum Abbrechen und einem Klick daneben.
- **„Abbrechen" bekommt den Fokus**, nicht „Ja". Wer aus Gewohnheit sofort Enter drückt,
  bricht ab, statt zu löschen.
- Am Verhalten ändert sich nichts: ohne Bestätigung passiert weiterhin nichts.

Der Dialog liegt in einer eigenen Vorlage (`_frage.html`) und wird von `base.html`
eingebunden — und von der öffentlichen VRC-Seite, die bewusst nicht von `base.html` erbt.
Dort kommen Fremde an, die gerade ihr VRChat-Konto bestätigen; ausgerechnet die sollen keine
Browser-Warnung mit fremder Domain sehen. Die Knopffarben stehen direkt am Dialog, weil jene
Seite nur die Grundklasse `.btn` kennt — sonst sähe „Abbrechen" dort aus wie die Hauptaktion.

**Einträge markieren, markierte löschen, Reihenfolge ändern**
- Gewünscht: „ich will bei einträgen zb auch die möglichkeit haben das mann sachen makieren
  kann und makierte löchen zu können" — und verschieben. Umgesetzt an den
  **Embed-Nachrichten**, der Liste aus der Meldung.
- Kästchen je Zeile, eins in der Kopfzeile für alle, und ein Knopf, der mitzählt
  („Markierte löschen (3)"). Beim Löschen verschwindet auch die geposteten Nachricht in
  Discord — derselbe Weg wie beim einzelnen X, nicht ein zweiter danebengebaut.
- Pfeile ↑ ↓ für die Reihenfolge. Am oberen und unteren Ende sind sie ausgegraut.

**Warum beim Verschieben die ganze Liste neu nummeriert wird**
Alle bestehenden Einträge stehen auf 0. Zwei Nullen zu tauschen wäre wirkungslos — beim
ersten Verschieben bekommt die Liste dieses Servers deshalb feste Plätze 1…n, und ab da ist
jeder weitere Schritt eindeutig. Andere Server bleiben dabei unberührt.

**Warum das Formular neben der Tabelle steht**
In den Zeilen stehen schon Formulare (Löschen, Bearbeiten), und verschachtelte Formulare
kennt HTML nicht. Die Kästchen gehören deshalb über ihr `form`-Attribut zu einem Formular
daneben.

**Geprüft:** 130 Prüfungen für den Dialog (kein `confirm`/`alert`/`prompt` mehr in den
Vorlagen, jede Seite die ihn benutzt bringt ihn auch mit, Fokus und Escape, und dass nach
einem Hinweis der Ja-Knopf zurückkommt) und 23 fürs Markieren und Verschieben (Unfug aus
dem Formular, Deckel bei 200, beide Ränder, fremde Zeilennummern, und dass ein anderer
Server unberührt bleibt).

**Nicht geprüft:** wie der Dialog im Browser aussieht.

---

## 1.19.41 — `beta` — 18.11.2026

**Dasselbe Backup lässt sich nicht mehr aus Versehen zweimal einspielen**
- Gemeldet: „ausversehen 3 mal das selbe backup eingespielt". Einspielen **legt an**, es
  gleicht nicht ab — dreimal dieselbe Datei heißt dreimal dieselben Reaction Roles,
  Befehle und Panels. Auffallen tut es erst hinterher, und aufräumen muss man von Hand.
- Jede exportierte Datei trägt jetzt eine **Kennung**. Wird sie ein zweites Mal auf
  denselben Server hochgeladen, wird sie abgelehnt — mit Datum, wer es war und welche
  Nummer sie hatte. Wer es wirklich will, setzt einen Haken neben dem Upload, auf dem
  steht, was dann passiert.

**Eine Nummer im Dateinamen**
`backup_server_MeinServer_nr0007_20261118_1430.json`. Gezählt wird je Server, nicht global:
„das siebte Backup dieses Servers" sagt etwas, wenn zwei Dateien nebeneinander liegen. Das
`(1)`, das der Browser anhängt, sagt nur etwas über die Reihenfolge des Herunterladens.

**Was absichtlich erlaubt bleibt**
Dieselbe Datei auf einem **anderen** Server einzuspielen ist kein Versehen, sondern der
Zweck des Server-Backups („einen Server an jemand anderen übergeben"). Dort entsteht nichts
doppelt, dort entsteht es zum ersten Mal. Gesperrt wird deshalb nur die Kombination aus
Datei **und** Server.

**Auch für alte Backups**
Dateien von vor dieser Version haben keine Kennung. Für die springt der Fingerabdruck der
Datei selbst ein — dieselbe alte Datei zweimal hochgeladen fällt damit genauso auf. Ein
Kopfeintrag, der keine saubere Kennung ist, wird verworfen statt geglaubt: sonst könnte eine
veränderte Datei behaupten, sie sei eine andere.

**Vermerkt wird erst nach dem Durchlauf**, nicht davor. Ein Einspielen, das unterwegs
abbricht, lässt sich damit noch einmal versuchen, ohne den Haken setzen zu müssen.

**Geprüft:** 30 Prüfungen. Die Kennung aus dem Kopf und der Fingerabdruck als Ersatz, sechs
Sorten Unfug im Kopfeintrag, die Nummernzähler je Server und getrennt fürs Komplett-Backup,
die Sperre auf demselben Server, die **fehlende** Sperre auf einem anderen, zweimal
vermerken ohne zweiten Eintrag — und dass die Meldung Nummer, Person und den Ausweg
wirklich nennt.

---

## 1.19.40 — `beta` — 18.11.2026

**Plugins können sich selbst aktualisieren**
- Gewünscht: „die plugins können auch selber eine version und github links haben das mann
  die plugins updaten kann". Ein Plugin nennt jetzt freiwillig eine `quelle` — die Adresse
  seiner jeweils neuesten Fassung — und eine `homepage` für Menschen.
- **Einstellungen → Plugins** fragt dort nach: je Plugin oder „Bei allen nachsehen". Liegt
  etwas Neueres, steht es da samt Knopf. Geladen und eingespielt wird nur auf Druck, und auf
  den Servern ändert sich weiterhin erst etwas, wenn dort jemand umstellt.
- **Einspielen über einen Link** statt über eine Datei. Ein gewöhnlicher GitHub-Seitenlink
  wird automatisch in die Rohadresse umgeschrieben — das ist die Stolperstelle, über die
  sonst jeder einmal fällt.

**Warum der Versionsvergleich zahlenweise ist**
Alphabetisch wäre `1.10.0` kleiner als `1.9.0`. Den Fehler merkt man erst bei der zehnten
Fassung, wenn plötzlich niemand mehr ein Update angeboten bekommt. „Neuer" heißt außerdem
echt größer: ein selbst bearbeitetes Plugin wird nie klammheimlich von einer älteren Fassung
an der Quelle überschrieben.

**Der Bot holt eine Adresse, die ein Fremder geschrieben hat**
Das ist eine Abfrage aus dem eigenen Netz heraus — also die Stelle, an der man sich ein Loch
hineinbaut, wenn man es laufen lässt. Deshalb: nur https, und nur Adressen im offenen Netz.
Private Adressen (`127.*`, `10.*`, `192.168.*`, `::1`) werden abgelehnt, **auch über eine
Weiterleitung** — jede Zwischenstation wird erneut geprüft statt blind verfolgt. Dazu Zeit-
und Größengrenze. Und: **die Kennung muss übereinstimmen.** Liegt unter der Adresse
inzwischen ein anderes Plugin, wird abgelehnt — sonst entstünde auf jedem Server, der das
alte benutzt, fremder Inhalt.

Eine `homepage` muss https sein. Ohne diese Prüfung könnte eine Datei dort
`javascript:…` hineinschreiben, und die Seite hätte daraus einen Knopf gemacht, der im
Browser des Admins etwas ausführt.

**Am Server steht jetzt, was angelegt wurde — mit Namen**
- Gewünscht: „wenn man ein plugin hinzufügt sollte dann das teil was hinzugefügt worden ist
  dann dort landen mit namen". Vorher stand dort nur, wie viele Einträge es sind. Die Frage,
  die man davor hat, ist aber eine andere: ist der Befehl dabei, den ich suche?
- Nachgeschlagen wird jede Zeile **in der echten Tabelle**, nicht in der Datei. Angezeigt
  wird also, was auf dem Server wirklich existiert.
- Hat jemand eine davon von Hand gelöscht, steht das auch da („2 Einträge sind nicht mehr
  da"), statt dass sie stillschweigend aus der Liste verschwindet.

**Geprüft:** 80 Prüfungen (vorher 53). Neu dabei: abgelehnte Adressen (http, ftp,
GitHub-Seite statt Datei, zu lang, ohne Rechnernamen), das Umschreiben von GitHub-Links, die
Abwehr von `localhost` und `127.0.0.1`, der Versionsvergleich inklusive `1.10.0` gegen
`1.9.0`, `javascript:` als Projektseite — und dass die Namensliste am Server stimmt und eine
von Hand gelöschte Zeile gemeldet wird.

---

## 1.19.39 — `beta` — 18.11.2026

**Plugins: Pakete aus Einstellungen, die man weitergeben kann**
- Gewünscht war ein Plugin-System, „damit Leute selber bauen können": in den Einstellungen
  Plugins mit Import und Export, dann auf einem Server hinzufügen, und dessen Einstellungen
  getrennt exportieren und einspielen.
- Ein Plugin ist eine JSON-Datei, die **beschreibt**, was angelegt werden soll: Befehle, ein
  Ticket-Panel samt Kategorien, Level-Rollen, Level-Belohnungen, Wortlisten. Der Bot legt es
  an. Nichts Bestehendes wurde umgebaut — wer kein Plugin einspielt, merkt von der Sache
  nichts.

**Warum kein Code ausgeführt wird**
Ein Python-Plugin liefe im selben Prozess wie der Bot: Bot-Token, ganze Datenbank samt
E-Mail-Adressen, Passwort-Hashes und 2FA-Geheimnissen der Dashboard-Konten, Dateien des
Wirts. Python bietet keine Abschottung, die das zuverlässig verhindert — wer hochladen darf,
hätte den Bot. Einen Tag nach der Umstellung auf einen Container ohne root wäre das der
Schritt zurück gewesen. Eine Beschreibung kann das nicht: sie wird gelesen, geprüft und in
genau fünf bekannte Tabellen geschrieben.

**Warum Platzhalter statt Nummern**
Ein Server-Backup darf Rollen- und Kanalnummern roh enthalten — es wandert von einem Server
zum nächsten. Ein Plugin soll auf Servern laufen, die sein Autor nie gesehen hat; dort wären
seine Nummern schlicht falsch. Es erklärt deshalb seine offenen Stellen selbst
(`einstellungen`) und setzt im Inhalt `{{platzhalter}}`. Ein Platzhalter, den das Plugin
nicht erklärt, lässt die Datei beim Hochladen durchfallen — sonst stünde er am Ende wörtlich
in einem Befehl.

**Entfernen nimmt nur das Eigene weg**
Zu jeder angelegten Zeile wird mitgeschrieben, aus welchem Plugin sie stammt. Ein Entfernen,
das stattdessen nach Namen oder Inhalt sucht, trifft früher oder später etwas, das jemand
von Hand angelegt hat. Ein von Hand geschriebener Befehl überlebt sogar ein Plugin, das
denselben anlegen wollte: er wird beim Anlegen übersprungen, also nicht mitgeschrieben, also
auch nicht gelöscht.

**Was bewusst nicht geht**
- **Reaction Roles** hängen an der Nummer einer bestehenden Nachricht — die kann kein Paket
  mitbringen, es zeigte auf jedem Server ins Leere.
- **Die Server-Einstellungen selbst** sind der Generalschlüssel (Rollen, Schalter, der
  Schlüssel der Profil-Schnittstelle). Eine Datei soll keine Funktionen anschalten können,
  die niemand bestellt hat.
- **Ein eingespieltes Ticket-Panel bleibt Entwurf.** Veröffentlichen postet eine Nachricht in
  einen Kanal — das löst ein Mensch aus, kein Datei-Upload.

**Neue Fassung heißt nicht sofortiges Umstellen**
Dieselbe Kennung nochmal hochzuladen aktualisiert das Plugin in der Installation, lässt die
Server aber auf ihrer Fassung stehen. Sie bekommen einen Hinweis und entscheiden selbst —
ein Upload soll nicht hinter ihrem Rücken ihre Zeilen ersetzen.

**Was zu tun ist**
Nichts. Der Reiter „🧩 Plugins" erscheint bei den Einstellungen und je Server; ohne
eingespieltes Plugin steht dort nur, wo man eines herbekommt. Das Format steht in der README,
eine Beispieldatei zum Abschreiben in `tools/plugin-beispiel.json`.

**Geprüft:** 53 Prüfungen gegen echte Tabellen — was abgelehnt werden muss (kaputtes JSON,
Server-Backup statt Plugin, fremdes Format, unbekannte Inhaltsart, unerklärte Platzhalter,
fehlende Pflichtfelder, zu große Dateien), das Einsetzen der Werte, und vor allem: dass
Anlegen nicht verdoppelt, Entfernen genau die eigenen Zeilen nimmt, Handarbeit stehen bleibt
und ein zweiter Server unberührt bleibt.

**Nicht geprüft:** die Oberfläche im Browser.

---

## 1.19.38 — `beta` — 18.11.2026

**Update scheiterte mit „exit 128", wenn der Projektordner fehlt**
- Gemeldet von einer fremden Installation beim Wechsel auf den Beta-Kanal. In der Ausgabe
  stand `fatal: cannot change to '/repo': No such file or directory`, darunter rot
  „git fetch fehlgeschlagen (exit 128)". Aus der Zahl liest niemand ab, dass schlicht ein
  Einhängepunkt fehlt.
- `/repo` ist der Projektordner des Wirts im Container — daraus holt das Update den Code.
  Fehlt in der `docker-compose.yml` die Zeile `- .:/repo`, oder wurde der Container noch
  mit einer älteren Fassung angelegt, ist der Ordner nicht da und kein git-Befehl kann
  gelingen.
- Geprüft wird das jetzt **vor** dem ersten git-Aufruf. Die Meldung sagt, was fehlt und
  was auf dem Wirt zu tun ist: Zeile prüfen, dann `docker compose up -d`.

**Warum ein Neustart dafür nicht reicht**
Docker übernimmt Einbindungen nur beim **Neuerstellen** eines Containers. Wer die
compose-Datei ändert und danach nur neu startet, hat weiterhin keinen `/repo`-Ordner — und
sucht den Fehler an der falschen Stelle. Das steht jetzt mit in der Meldung.

Unter Android greift die Prüfung nicht: dort läuft das Update über den APK-Download, einen
Projektordner gibt es gar nicht.

---

## 1.19.37 — `beta` — 17.11.2026

**Die Befehlsliste spricht jetzt die Sprache der Person**
- Gemeldet waren zwei deutsche Befehlsnamen auf einem englischsprachigen Server. Beim
  Nachsehen war es mehr: deutsch sind nur **vier Namen** (`/bewerten`, `/bewertungen`,
  `/profil`, `/profil-loeschen`) — die **Beschreibungen** aber bei **allen 39** Befehlen.
  Unter jedem englisch benannten Befehl stand ein deutscher Satz.
- Discord kann beides je Sprache ausliefern. Englische Clients sehen ab jetzt `/rate`,
  `/ratings`, `/profile`, `/profile-delete` samt englischen Beschreibungen und
  Parameternamen (`grund` → `reason`, `sterne` → `stars`); deutsche Clients alles wie
  bisher.
- **Maßgeblich ist die Client-Sprache der Person, nicht `bot_lang` des Servers.** Ein
  Deutscher auf einem englischsprachigen Server sieht weiter Deutsch. Das ist Absicht: die
  Befehlsliste gehört zur Oberfläche dessen, der sie aufklappt.
- Andere Sprachen bekommen den deutschen Standardtext — lieber Deutsch als Kauderwelsch.

**Ohne Eingriff in die Befehle selbst**
discord.py wandelt Namen, Beschreibungen, Parameter und Auswahleinträge von sich aus in
übersetzbare Zeichenketten um. Es brauchte deshalb keinen Eingriff in die 39 Befehle,
sondern eine Übersetzungstabelle (`app/befehlstexte.py`) und einen Übersetzer, der nur auf
Englisch antwortet.

**Was zu tun ist**
Sichtbar wird es beim nächsten Start des Bots — dann wird die Befehlsliste neu abgeglichen.

**Nicht geprüft:** wie es in Discord wirklich aussieht. Der Test prüft die Übersetzungen,
die Regeln für Namen (ein einziger ungültiger ließe den Abgleich scheitern, und dann hätte
der Server **gar keine** Befehle mehr) und dass der Übersetzer vor dem Abgleich gesetzt wird.

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
  Installationen im selben Verzeichnis wie das Repo (`data-<name>/`).
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
