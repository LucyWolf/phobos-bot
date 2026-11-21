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

## 1.19.59 — `beta` — 21.11.2026

**VRC-Link-Debug: aus dem Datenpunkt-Fenster wird eine Konsole**
Das 🐞-Fenster (1.19.58) ist jetzt eine kleine Debug-Kommandozeile — **zentriert** statt links
angedockt. Statt nur Datenpunkte zu suchen, kennt sie Befehle:
- `data <name>` — die Datenpunkte, die ein Plugin aus der Quelle „vrchat" bekäme (nur
  bestätigte Verknüpfungen, nur die vier Felder).
- `status <name>` — der volle Verknüpfungs-Status, auch wartende und ungelöste, um Probleme zu
  sehen: Status, Eigentumsnachweis, Zeitpunkte, Rollen-Sync, Notiz.
- `help` — die Befehlsliste.

**Es ist eine Attrappe, kein Terminal**
Die Konsole kennt nur diese drei Wörter. Kein Shell-Zugang, kein `eval`, kein `subprocess` —
was nicht genau „data", „status" oder „help" ist, ergibt „unknown command". Die Eingabe löst
nur feste, parametrisierte Datenbank-Abfragen aus; Tabellen- und Spaltennamen stehen im Code,
nie in der Eingabe. Nur für Server-Admins, nur beim VRC-Link. Fremde Namen/Notizen werden in
der Anzeige als Text behandelt, nie als HTML.

**Doku**
- README (EN + DE): der Hinweis im Daten-Abschnitt nennt jetzt die Konsole und ihre Befehle.

## 1.19.58 — `beta` — 21.11.2026

**Neu: „Plugin data points" — Debug-Fenster im VRC-Link-Reiter**
Wer ein Plugin baut, das die Quelle „vrchat" liest, musste bisher raten, welche Werte dort
ankommen — oder erst ein Plugin einspielen, freigeben und eine Welt bauen. Jetzt steht im Kopf
des VRC-Link-Reiters ein drittes Icon (🐞) neben ℹ und ⚠. Es klappt ein Fenster auf, in das man
einen VRChat-Namen eingibt (ein Teil reicht) und die Datenpunkte dieser Person sieht, genau wie
ein Plugin sie bekäme: `trust`, `verifiziert_18`, `supporter`, `gruppenmitglied`. Passen mehrere
Namen, erscheinen mehrere Treffer.

**Dieselben Schranken wie die echte Daten-Schnittstelle**
- Nur bestätigte Verknüpfungen, nur diese vier Felder, keine Discord-IDs — was ein Plugin nicht
  lesen darf, zeigt auch dieses Fenster nicht.
- Nur für Server, die man verwalten darf (dieselbe Zugriffsprüfung wie der ganze Reiter).
- Der VRChat-Name wird beim Anzeigen gegen HTML abgesichert.

**Doku**
- README (EN + DE): ein nur-lesendes VRC-Link-Beispielplugin im Abschnitt „A plugin can also read
  data", mit Hinweis auf das neue Debug-Fenster.

## 1.19.57 — `beta` — 19.11.2026

**Plugin-Karte unter Einstellungen → Plugins kompakt gemacht**
- Gemeldet: die Karte ist überladen, die Info soll kurz sein — die Details sieht und
  schreibt man am Server. Umgesetzt:
- Die **Beschreibung** ist auf zwei Zeilen begrenzt, egal wie lang ein Autor schreibt.
- Die **lange Bezugs-URL** ist von der Karte weg (der „Nach Update suchen"-Knopf braucht
  sie intern weiter, zeigt sie aber nicht mehr an).
- Der **Hinweis „An/aus je Server …"** stand bei jeder Karte — jetzt nur noch **einmal
  oben** über der Liste.
- Geblieben: Icon, Name, Version, die Knöpfe, und die kompakten Badges (was das Plugin
  anlegt, wie viele Einstellungen, auf wie vielen Servern).

Bei Rollen-/Kanal-Plugins bleibt die Server-Wahl an der Karte, weil sie dort gebraucht wird.

---

## 1.19.56 — `beta` — 19.11.2026

**Plugin-Einstellungen gehören zum Server, nicht zentral**
- Unter Einstellungen → Plugins steht jetzt nur noch das Plugin selbst: hochladen,
  exportieren, löschen, nach Update suchen. Das Werte-Formular (z. B. „Was soll der Befehl
  antworten?") ist dort **weg** — gewünscht: „dabei sollte nur das plugin sein, einstelungen
  immer noch intern im den jeweiligen server".
- Die Werte setzt man jetzt **beim jeweiligen Server**: Plugin in der Leiste anklicken, dort
  das Feld ausfüllen. Jeder Server hat seine eigenen — so wie es sein soll.
- Angehakt wird weiterhin je Server in den Angezeigten Funktionen; beim Anhaken greifen die
  Standardwerte, anpassen tut man sie dann am Server.
- Die zentrale Werte-Route von 1.19.54 ist damit wieder raus.

**Kleiner Aufräumer von 1.19.55 mit dabei**
Die „Läuft auf"-Server-Pillen stehen nur noch bei Rollen-/Kanal-Plugins (wo sie zur
Server-Konfiguration führen), nicht beim Text-Plugin.

**Geprüft:** die 13 + 114 + 12 Plugin-Prüfungen bleiben grün.

**Nicht geprüft:** das Aussehen im Browser.

---

## 1.19.55 — `beta` — 19.11.2026

**Plugin-Seite: die „Läuft auf"-Serverliste beim Text-Plugin entfernt**
Seit ein Text-Plugin je Server in den „Angezeigten Funktionen" an- und abgehakt wird, waren
die Server-Pillen unter Einstellungen → Plugins doppelt — wie viele Server es sind, steht
ohnehin im Hinweis darunter. Die Pillen bleiben nur noch bei Rollen-/Kanal-Plugins, wo sie
der Weg zur Konfiguration je Server sind.

---

## 1.19.54 — `beta` — 19.11.2026

**Plugins werden jetzt wie eine Funktion je Server an- und abgehakt**
- Gewünscht: ein eingespieltes Plugin soll auf allen Servern verfügbar sein und dann
  **in den „Angezeigten Funktionen" je Server** aktiviert oder deaktiviert werden —
  genau wie Willkommen, Tickets und die anderen. Kein „Server wählen", kein „alle
  Server"-Knopf mehr.
- Jedes eingespielte Plugin (ohne Rollen-/Kanal-Feld) steht nun im Funktions-Kasten des
  Config-Reiters als eigener Haken, mit Icon und Namen. **Haken dran** = auf diesem Server
  angelegt und in der Leiste; **Haken weg** = wieder entfernt.
- Die Werte (z. B. die Antwort deines Test-Plugins) setzt man **einmal zentral** unter
  Einstellungen → Plugins. Sie gelten dann auf jedem Server gleich. Ändert man sie, werden
  alle Server, auf denen das Plugin aktiv ist, gleich mit aufgefrischt.

**Der „Auf allen Servern anlegen"-Knopf ist weg**
Braucht man nicht mehr — das An/Aus je Server macht das sauberer. Unter Einstellungen →
Plugins steht bei einem Text-Plugin jetzt nur noch das Werte-Formular mit „Speichern" und
der Hinweis, dass das Ein- und Ausschalten im Config-Reiter sitzt.

**Rollen-/Kanal-Plugins bleiben außen vor**
Ein Plugin, das eine Rolle oder einen Kanal abfragt, taucht **nicht** in den Haken auf —
seine Werte sind pro Server verschieden, das ließe sich nicht mit einem Haken für alle
setzen. Solche Plugins behalten die Auswahl je Server (Menü unter Einstellungen → Plugins).

**Und der tote Eintrag von vorhin**
Das generische „🧩 Plugins" ist aus den Angezeigten Funktionen raus (steuerte nichts mehr).

**Geprüft:** 13 neue Prüfungen am Haken-Modell (nur Text-Plugins erscheinen, Anhaken legt
mit den zentralen Werten an, Abhaken entfernt, ein anderer Server bleibt unberührt, der
Standard greift ohne gesetzte Werte) plus die 114 + 12 + 8 bestehenden Plugin-Prüfungen.

**Nicht geprüft:** das Aussehen im Browser.

---

## 1.19.53 — `beta` — 19.11.2026

**Plugins: „Auf allen Servern anlegen" statt Server-für-Server, und ein toter Eintrag weg**
- Gemeldet: in den „Angezeigten Funktionen" stand noch ein Kästchen „🧩 Plugins". Seit die
  Plugins einzeln mit Namen und Icon in der Leiste stehen, gibt es keinen Sammel-Reiter mehr
  zum Aus- oder Einblenden — das Kästchen steuerte nichts. Raus damit. Die
  Moderator-Rechtesteuerung („darf dieser Mod Plugins sehen?") bleibt.
- Gewünscht: ein Plugin soll gleich auf allen Servern gelten, ohne „Server wählen". Umgesetzt
  für Plugins **ohne serverspezifische Felder**: unter Einstellungen → Plugins stehen die
  Einstellungen direkt da, dazu ein Knopf **„Auf allen Servern anlegen"**. Ein Klick, überall
  angelegt.

**Warum nicht für jedes Plugin**
Ein Plugin, das eine **Rolle, einen Kanal oder eine Kategorie** abfragt, kann nicht auf allen
Servern denselben Wert haben — welche Rolle auf Server B gemeint ist, weiß nur dieser Server.
Solche Plugins behalten die Auswahl je Server; der „alle Server"-Weg lehnt sie mit einem
klaren Satz ab, statt leere Nummern anzulegen. Die Seite zeigt automatisch den richtigen
Weg: Textfeld-Plugins den Knopf, Rollen-Plugins das Menü.

**Geprüft:** 114 Plugin-Prüfungen (vorher 109). Neu: dass Textfelder und „keine Einstellung"
keine Server-Wahl brauchen, Rolle/Kanal/Kategorie dagegen schon. Die Leisten-Prüfungen und
die Kern-Kette bleiben grün.

**Nicht geprüft:** das Aussehen im Browser.

---

## 1.19.52 — `beta` — 19.11.2026

**Ressourcengrenzen: CPU dazu, und eine Schritt-für-Schritt-Anleitung**
- Entschieden wurde: kein Einstellfeld im Dashboard. Der Bot kann seine eigenen
  Container-Grenzen nicht selbst setzen — das ginge nur über den Docker-Socket, und der ist
  genau der root-Weg, den wir abgeschafft haben. Also bleibt es dort, wo Docker es liest: in
  der `docker-compose.yml`, standardmäßig aus.
- Zur RAM- und Prozessgrenze (1.19.51) kommt jetzt eine CPU-Grenze (`cpus`), ebenfalls
  auskommentiert. Mit dem ehrlichen Hinweis dabei: **CPU ist anders als RAM eine echte
  Drossel**, kein Dach gegen Ausreißer — nur setzen, wer den Bot bewusst zügeln will.
- Neu in der README, beide Sprachen: ein eigener Abschnitt **„Ressourcengrenzen (für kleine
  Maschinen) — Schritt für Schritt"**. Sechs Schritte vom Nachsehen des Verbrauchs
  (`docker stats`) über das Wählen und Eintragen der Werte bis zum Anwenden, Prüfen und dem,
  was zu tun ist, wenn der Bot ständig neu startet (Grenze zu niedrig, Exit 137). Verlinkt
  aus den Pi-Hinweisen und im Inhaltsverzeichnis.

Nichts am Bot-Code geändert — compose-Vorlage und README.

---

## 1.19.51 — `beta` — 19.11.2026

**Obergrenzen gegen Ausreißer — für kleine Maschinen, standardmäßig aus**
- Zwei Zeilen in der `docker-compose.yml` vorbereitet (`mem_limit`, `pids_limit`),
  **auskommentiert**. An einer gewöhnlichen Installation ändert sich damit nichts.
- Es ist **keine Drosselung**: der Bot nimmt sich im Normalbetrieb, was er braucht (meist
  unter 300 MB, eine Handvoll Prozesse), und merkt die Grenzen nie. Sie greifen nur, wenn
  etwas ausbricht — ein Speicherleck, oder durch einen Fehler plötzlich tausend Prozesse.
  Dann stoppt Docker **nur diesen** Container, statt dass er die ganze Maschine mitnimmt.
  Dasselbe Prinzip wie die Log-Grenze, nur für RAM und Prozesse.
- Gedacht für **Raspberry Pi 4/5** und ähnliche kleine Maschinen, wo oft mehrere Container
  um knappen Speicher konkurrieren. Einkommentieren, `mem_limit` an die Maschine anpassen,
  einmal `docker compose up -d`. Der Hinweis steht auch im Pi-Abschnitt der README.

Nichts am Bot-Code geändert — nur die Vorlage und ihre Erklärung.

---

## 1.19.50 — `beta` — 18.11.2026

**Plugins stehen in der Server-Leiste jetzt mit Namen und Icon, nicht als „Plugins"**
- Gemeldet: der generische Reiter „🧩 Plugins" soll dort weg — „wenn man bei plugins was
  rein lädt dann sollte direkt der name mit icon stehen wie ich das schon gesagt hatte".
- Ab jetzt steht in der Server-Leiste **je angelegtem Plugin ein eigener Eintrag** mit
  seinem Icon und Namen. Kein Sammel-Reiter mehr. Läuft kein Plugin auf dem Server, steht
  dort auch nichts.
- Ein Klick auf den Eintrag öffnet direkt die Einstellungen genau dieses Plugins
  (Werte, Datenfreigabe, Entfernen).

**Ein Plugin darf ein Icon mitbringen**
Im Format neu: `"icon": "🎮"`. Freiwillig; ohne Angabe steht das Puzzleteil 🧩 davor.
Buchstaben und ganze Sätze werden abgewiesen und durch das Standard-Icon ersetzt — sonst
stünde ein Textschnipsel in der Navigation, der aussieht wie ein Fehler.

**Hinzugefügt wird jetzt zentral**
Weil es keinen Sammel-Reiter mehr gibt, passiert das Anlegen unter **Einstellungen →
Plugins**: dort je Plugin ein Menü „Auf einem Server anlegen". Die Auswahl führt auf den
Server, wo das Formular mit dessen Rollen und Kanälen steht — dort, wo diese Angaben
überhaupt verfügbar sind. Schon laufende Server stehen daneben und führen direkt zu ihren
Einstellungen.

**Was das für Moderatoren-Rechte heißt**
Wer einem Moderator den Reiter „plugins" nicht freigegeben hat, sieht die Plugin-Einträge
weiterhin nicht — die Steuerung bleibt, nur der eine generische Eintrag wird zu mehreren
benannten.

**Geprüft:** 12 neue Prüfungen an der echten Leisten-Vorlage und an der Abfrage dahinter
(je angelegtem Plugin ein Eintrag mit Icon+Name, der zum richtigen Plugin führt; kein
generischer Eintrag mehr; ein gesperrter Moderator sieht nichts; ein fremder Server bleibt
leer; ohne eigenes Icon das Puzzleteil). Dazu 5 Prüfungen am Format fürs Icon. Die
bestehenden 104 Plugin-Prüfungen bleiben grün.

**Nicht geprüft:** das Aussehen im Browser.

---

## 1.19.49 — `beta` + `main` — 18.11.2026

**Zehn Durchgänge über den Verknüpfungslink — zwei echte Fehler**

*Ein Doppelklick auf den Knopf in Discord ergab eine Seite, die nicht funktioniert*
- Zwei Anfragen mit demselben Schlüssel können gleichzeitig ankommen. Beide lasen die Zeile
  als gültig, beide tauschten — nur eine traf noch etwas. Die zweite schrieb ihren frischen
  Schlüssel trotzdem in die Seite: **lauter Formulare mit einem Schlüssel, den es nirgends
  gibt.** Eine Seite, die heil aussieht und bei jedem Knopf ins Leere läuft.
- Jetzt entscheidet der Rückgabewert des Tauschs. Wer zu spät kommt, bekommt dieselbe
  Antwort wie bei einem abgelaufenen Link — ehrlich statt kaputt.

*Ein toter Knopf im Wartezweig*
- Braucht ein Server die Freigabe durch die Moderation, landet man nach der Bestätigung im
  Wartezweig — und dort stand weiterhin „Anderes Konto verknüpfen". Der Schlüssel ist zu dem
  Zeitpunkt gelöscht, der Knopf hätte nur die Abgelaufen-Seite gezeigt. Im Done-Zweig hatte
  ich das abgefangen, hier nicht.

**Aufgeräumt: ein Test, der nichts prüfte**
`test_vrcweb.py` führt die **echten** Routen gegen eine echte Datenbank und die echte Seite
aus — laut dem Commit von v1.17.2 mit 74 Fällen. Die Fälle sind irgendwann aus der Datei
verschwunden; übrig blieb ein Gerüst, das alles lädt und **nichts** prüft. Es meldete
stillschweigend „grün", und das ist schlimmer als rot.

Wieder aufgebaut mit 22 Fällen rund um die Frage, um die es gerade geht. Dabei fiel auf,
dass das Gerüst selbst veraltet war: die VRChat-Attrappe nahm das Server-Konto nicht an, das
der Cog inzwischen mitgibt. Unbemerkt geblieben, weil die Datei ja nichts ausführte.

Geprüft wird jetzt am laufenden Code: dass das Öffnen den Schlüssel tauscht, dass der aus
der Adresse weder auf der Seite noch in der Datenbank übrig bleibt, dass ein zweites Öffnen
**und** jeder POST mit dem alten Schlüssel abgewiesen wird, dass zwei gleichzeitige
Öffnungen genau einmal gelingen, dass abgelaufen und erfunden gleich aussehen, dass ein
abgeschalteter Server sofort sperrt, dass die vier Schutz-Kopfzeilen an jeder Antwort hängen
— und dass der Schlüssel nirgends in einer Adresse der Seite steht, nur in Formularfeldern.

**Beim Durchgehen geprüft und in Ordnung befunden**
Die Bremse zählt nach dem Tausch weiter richtig (sie wird erst in den POST-Schritten
angefasst). Die Frist verlängert sich beim Tauschen nicht. Es bleibt bei einer Zeile je
Person. Der Zeitpunkt des Öffnens (`used_at`) wird festgehalten und von nichts gelesen —
das bleibt bewusst so: er beantwortet die eine Support-Frage, die sonst niemand beantworten
kann, nämlich ob jemand seinen Link überhaupt je geöffnet hat.

---

## 1.19.48 — `beta` + `main` — 18.11.2026

**Der Schlüssel aus der Adresse wird beim Öffnen getauscht**
- Nachgefragt wurde, ob die Einmal-Regel von 1.19.47 wirklich sicher ist. Sie war es nur
  halb: das **Öffnen** war verbraucht, der Schlüssel selbst stand aber weiter in der
  Datenbank — und alle Schritte der Seite laufen über POST, die prüfen das Öffnen nicht.
  Wer die Adresse hatte, konnte also weiterhin von Hand eine Anfrage schicken, solange der
  Vorgang lief.
- Jetzt bekommt die Zeile beim Öffnen einen **frischen Schlüssel**, der nur in den
  Formularen dieser einen Antwort steht. Der aus der Adresse existiert danach nicht mehr —
  weder fürs Öffnen noch für irgendeine POST-Route. Eine Adresse aus einem Protokoll, einem
  Verlauf oder einem weitergeleiteten Screenshot ist damit **tot**, nicht bloß „nicht mehr
  anzeigbar".

**Ohne Cookie, wie gewünscht**
Das ist das Token-Drehen aus v1.17.1 — damals mit Cookie, weil es eine Weiterleitung
brauchte, um die Adresszeile zu säubern, und eine Weiterleitung etwas braucht, das den
Besucher trägt. Hier wird nicht weitergeleitet, sondern direkt ausgeliefert: der frische
Schlüssel reist im Rumpf der Formulare, es gibt nichts zu tragen. **Es war also doch ohne
Cookie möglich.**

**Warum nur beim Öffnen und nicht bei jedem Schritt**
Ein Schlüssel, der sich mit jeder Antwort ändert, macht die Zurück-Taste und einen doppelten
Klick zur Sackgasse — mitten in einem Ablauf, bei dem man zwischendurch zu VRChat und zurück
muss. Das Risiko sitzt in der **Adresse**, und die gibt es genau einmal.

**Dazu beim Durchsehen**
- `X-Robots-Tag: noindex, nofollow, noarchive` ergänzt. Billig, ohne Nebenwirkung — sollte
  so eine Adresse je bei einem Crawler landen, wäre ein Suchtreffer dauerhaft, auch wenn der
  Schlüssel längst weg ist.
- Nachgesehen und in Ordnung: der Link wird als **Discord-Knopf** verschickt, nicht als Text
  in der Nachricht. Discord erzeugt für Knopf-Adressen keine Vorschau, holt sie also nicht
  selbst ab — sonst hätte die Vorschau den Schlüssel verbraucht, bevor ein Mensch klickt.
- Ebenfalls geprüft: `Referrer-Policy: no-referrer` (die Adresse reist zu nichts mit, was man
  von der Seite aus anklickt), `Cache-Control: no-store` (ein geliehener Browser hält die
  Seite nicht für den Nächsten bereit), `X-Frame-Options: DENY`.

**Was offen bleibt, ehrlich gesagt**
Der Link steht weiterhin **einmal** in der Adresszeile, im Verlauf und im Zugriffsprotokoll
des Proxys — ein Link kann seinen Schlüssel nicht anders tragen. Neu ist: er ist in dem
Moment, in dem die Seite aufgeht, bereits verbraucht. Wer ihn später dort findet, hat nichts
davon.

**Geprüft:** 35 Prüfungen. Dass getauscht und nicht nur markiert wird, dass der frische
Schlüssel in die Antwort kommt, dass die POST-Schritte **nicht** erneut tauschen (sonst wäre
die Zurück-Taste eine Sackgasse), dass die Route keine Weiterleitung baut (die bräuchte ein
Cookie) — und an echten Zeilen: dass der Schlüssel aus der Adresse hinterher nirgends mehr
zu finden ist, die Frist sich dabei nicht verlängert und es bei einer Zeile je Person bleibt.

---

## 1.19.47 — `beta` + `main` — 18.11.2026

**Der Verknüpfungslink gilt für ein einziges Öffnen und ist danach weg**
- Gemeldet von außen und als Gefahr eingestuft: „der link zum registrieren solte nur einmal
  benutzt werden dann wieder schliessen" / „der link darf danach nicht mehr existieren weil
  das eine gefahr sein könnte".
- Bisher blieb die Adresse die volle Stunde abrufbar — auch lange nachdem die Person fertig
  war. Wer sie in dem Fenster in die Finger bekam (weitergeleitete Nachricht, Blick über die
  Schulter, geteilter Bildschirm, Verlauf), sah die Abschluss-Seite mit **Discord-Name,
  VRChat-Name, Spitznamen und Prüfmerkmalen**.
- **Öffnen geht jetzt einmal.** Ein zweiter Aufruf bekommt dieselbe Seite wie ein
  abgelaufener Link: „hol dir einen neuen".
- **Nach der Bestätigung wird der Schlüssel gelöscht**, nicht nur als verbraucht vermerkt.
  Eine Zeile, die es nicht mehr gibt, kann auch kein späterer Fehler wieder aufmachen.

**Warum die Zwischenschritte weiterlaufen**
Verbraucht wird nur das **Öffnen**. Die Schritte danach gehen über POST und tragen den
Schlüssel im Rumpf — die gelten bis zum Ablauf weiter. Sonst wäre der Vorgang nach dem
ersten Klick zu Ende, und zwischen „Namen eintragen" und „Code in den Status setzen" liegt
ein Ausflug nach VRChat, von dem man zurückkommen muss.

**Keine toten Knöpfe**
Nach dem Löschen würden „Einladung anfordern", „Aktualisieren" und „Anderes Konto
verknüpfen" beim Klick nur noch die Abgelaufen-Seite zeigen. Sie werden deshalb nicht mehr
angezeigt; stattdessen steht da ein Satz, wie man wiederkommt: `/vrc-link` gibt jederzeit
einen frischen Link.

**Was das kostet**
Wer die Seite später noch einmal braucht — Gruppeneinladung nachfordern, Konto wechseln —,
holt sich einen neuen Link. Das ist ein Schritt mehr und die bewusste Gegenseite dieser
Entscheidung.

Bestehende Links aus der Zeit davor gelten weiter und werden beim nächsten Öffnen einmal
verbraucht, statt mit dem Update sofort tot zu sein.

**Geprüft:** 24 Prüfungen. Dass die Weiche im Öffnen sitzt und nicht in den POST-Schritten
(sonst käme niemand mehr durch), dass `_vrc_token_row` sie nicht über Umwege doch anwendet,
dass die Zeile nach der Bestätigung **gelöscht** und nicht nur markiert wird, dass das erst
nach dem Vergeben der Rolle passiert, dass die Abschluss-Seite trotzdem noch gebaut wird —
und dass ein Fehler beim Vermerken niemanden aussperrt.

---

## 1.19.46 — `beta` + `main` — 18.11.2026

**Dringend: der Nachfrage-Dialog sperrte Leute auf der öffentlichen VRC-Seite ein**
- Gemeldet von jemandem, der nur den Verknüpfungs-Link geöffnet hatte: „irgendwas stimmt
  mit der seite nicht / das fenster geht garnicht weg / hatte nur den link geöffnet und war
  dann schon stuck there". Die Seite war damit **unbenutzbar** — weder verknüpfen noch
  wegklicken.
- Ursache: Die Gestaltung des Dialogs stand im `style`-Attribut des Elements, darunter
  `display:flex`. **Ein `display` im Attribut überstimmt das `hidden`-Merkmal des
  Browsers.** Der Kasten stand also ab dem Laden offen, und „Abbrechen" setzte zwar
  `hidden`, was aber nichts bewirkte.
- Auf dem Dashboard fiel es nicht auf: `base.html` bringt eine eigene Regel
  `[hidden] { display:none !important }` mit und hat den Fehler zugedeckt. Die öffentliche
  Seite erbt nicht von `base.html` und hat diese Regel nicht — deshalb traf es genau die
  Seite, auf der Fremde ankommen.
- Der Dialog bringt seine Gestaltung jetzt als eigenen `style`-Block mit, **samt eigener
  `[hidden]`-Regel**, und verlässt sich auf nichts, was die einbindende Seite mitbringt.

**Was ich daraus mitnehme**
Eine gemeinsame Vorlage in zwei verschiedene Seiten einzubinden heißt, dass sie ohne die
Umgebung der einen auskommen muss. Geprüft hatte ich, dass der Dialog eingebunden *ist* —
nicht, ob er dort auch zu bleibt.

**Geprüft:** 12 neue Prüfungen, die genau das festhalten: dass die Überlagerung mit `hidden`
startet, ihre eigene `[hidden]`-Regel mitbringt, und dass `display` und `position` **nicht**
wieder ins `style`-Attribut wandern. Dazu, dass es drei Wege wieder hinaus gibt (Abbrechen,
Escape, Klick daneben).

**Diese Fassung geht sofort auch auf `main`** — die öffentliche Seite ist nichts, wo man auf
den nächsten geplanten Stand wartet.

---

## 1.19.45 — `beta` — 18.11.2026

**Das Ziehen hatte drei Fehler**
Gemeldet als „das klicken und verschieben hat bucks". Beim Durchgehen waren es drei, der
erste davon der, den man sieht:

*Die Liste sprang hin und her*
- Es wurde die Zeile genommen, die gerade **unter dem Zeiger** lag, und davor eingefügt.
  Damit liegt die gezogene Zeile selbst unter dem Zeiger, beim nächsten Mausereignis eine
  andere — und die Liste zappelte im Takt der Bewegung.
- Jetzt wird die Einfügestelle aus der **Mausposition über allen Zeilen** berechnet, nicht
  aus dem, was zufällig darunter liegt. Und steht die Zeile schon richtig, passiert gar
  nichts mehr.

*Ein abgebrochener Zug ließ eine falsche Anzeige stehen*
- Escape oder Loslassen außerhalb der Liste: gespeichert wurde nichts, die verschobene
  Vorschau blieb aber stehen. Beim nächsten Aufruf war alles wieder anders.
- Jetzt lädt die Seite in dem Fall neu. Eine Anzeige, die etwas anderes zeigt als
  gespeichert ist, ist schlimmer als gar keine.

*Der Tooltip klebte am Zeiger*
- Der Hinweis „zum Umsortieren festhalten und ziehen" hing an **jeder** Zeile und folgte
  beim Arbeiten dauernd der Maus. Er steht jetzt nur noch einmal unter der Tabelle.

**Markieren und Sortieren jetzt auch bei den Tickets**
- Gewünscht: „das bei einbetten nachrichten das mit den auswählen auch rein machen in
  tikets". Zwei Listen, zwei verschiedene Bedürfnisse:
- **Ticket-Panels**: ankreuzen, markierte löschen, Reihenfolge per Pfeil oder Ziehen — wie
  bei den Embed-Nachrichten. Gelöscht wird auch die gepostete Nachricht im Kanal.
- **Offene Tickets**: ankreuzen, dann **schließen** (räumt die Kanäle auf, wie beim
  einzelnen Schließen) oder **aus der Liste nehmen** (lässt die Kanäle stehen). Umsortieren
  gibt es hier nicht — offene Tickets stehen nach Eingang, und das ist richtig so.
- Beim Sammel-Schließen läuft jedes Ticket für sich. Klemmt eines — fehlende Rechte, Kanal
  schon weg —, laufen die anderen trotzdem durch, und am Ende steht da, wie viele es waren.

**Ein Fehler, der dabei fast entstanden wäre**
Der Dialog schickt ein Formular über dessen eigene Adresse ab; ein `formaction` am Knopf
zählt nur beim echten Klick. „Markierte aus der Liste nehmen" wäre damit beim **Schließen**
gelandet — lautlos und mit ganz anderer Wirkung. Der Dialog beachtet die Adresse des Knopfes
jetzt, und ein Test hält das fest.

**Geprüft:** 49 Prüfungen (vorher 38). Die drei Fehler von oben sind einzeln festgehalten,
damit sie nicht zurückkommen, dazu: vier Sammelknöpfe sind ohne Markierung abgeschaltet, die
vier Pfeile ausdrücklich **nicht** — sonst ließe sich ohne Markierung nichts mehr verschieben.

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
