#!/bin/sh
# Startskript des Containers. Einziger Zweck: den Bot NICHT als root laufen lassen.
#
# Bis v1.19.28 lief "python main.py" als uid 0, weil im Dockerfile nie eine USER-Zeile
# stand. Das war nie Absicht, sondern der Docker-Standardfall. Root im Container ist kein
# Einstieg fuer sich - es gibt keinen Docker-Socket und keine erhoehten Rechte (siehe
# Commit 10cb891) - aber es macht jeden Fehler schlimmer, als er sein muesste: wer den
# Prozess dazu bringt, eine Datei zu schreiben, schreibt sie als root in das eingehaengte
# Repo, also in den Code, der beim naechsten Start laeuft.
#
# Warum ein Skript und nicht einfach "USER phobos" im Dockerfile:
# Die Verzeichnisse /app, /app/data und /repo kommen per Bind-Mount vom Wirt. Ihre
# Besitzrechte stehen im Image NICHT fest - bei jeder bestehenden Installation gehoeren
# sie root. Eine blosse USER-Zeile haette genau dort zugeschlagen, wo es am meisten weh
# tut: der Bot startet, kann aber die Datenbank nicht mehr schreiben.
#
# ───────────────────────────────────────────────────────────────────────────────
# OBERSTE REGEL: Der Bot startet. Immer.
#
# Dieses Skript laeuft auf fremden Servern, auf Wirten mit anderen Besitzrechten, auf
# Dateisystemen, auf denen chown gar nicht geht (NFS, Docker Desktop unter Windows,
# exFAT auf einem USB-Datentraeger). Wenn hier irgendetwas nicht klappt, ist die richtige
# Antwort "dann eben wie bisher als root, und sag es laut" - und niemals ein Container,
# der in einer Neustartschleife haengt und ein ganzer Discord-Server steht.
#
# Deshalb: kein "set -e", jeder Schritt einzeln abgefangen, und bevor die Rechte wirklich
# abgegeben werden, wird VORHER geprueft, ob das auch gutgeht. Nach "exec" gibt es keinen
# Rueckweg mehr - also muss alles davor stimmen.
# ───────────────────────────────────────────────────────────────────────────────
#
# Durch "exec" bleibt Python PID 1 - das Aufraeumen verwaister git-Kindprozesse in
# main.py (_reap_stray_zombies) haengt daran und wuerde sonst ins Leere laufen.

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

sag() {
    echo "[start] $*"
}

starte_als_root() {
    cd /app || exit 1
    exec python main.py
}

# ── Faelle, in denen es nichts abzugeben gibt ────────────────────────────────
# Wer in der compose-Datei schon "user:" gesetzt hat, ist hier nie root. Dann waere
# jeder Versuch, Besitzrechte zu aendern, nur ein Fehler - und der Zustand ist ohnehin
# genau der gewuenschte.
if [ "$(id -u)" -ne 0 ]; then
    sag "laeuft bereits als uid $(id -u) - nichts abzugeben"
    starte_als_root
fi

# Notausgang. Wenn bei irgendeiner Installation etwas klemmt, kommt sie damit wieder
# hoch, ohne das Image zurueckbauen zu muessen. Absichtlich laut, damit niemand
# jahrelang unbemerkt als root laeuft, weil er das einmal zum Testen gesetzt hat.
if [ "$PHOBOS_ROOT" = "1" ]; then
    sag "ACHTUNG: PHOBOS_ROOT=1 gesetzt - der Bot laeuft als root. Nur als Notbehelf gedacht."
    starte_als_root
fi

# setpriv steckt in util-linux und ist in python:3.11-slim enthalten. Fehlt es trotzdem
# (fremdes Basis-Image), ist ein laufender Bot besser als ein Container, der gar nicht
# mehr startet - aber die Zeile muss im Protokoll stehen.
if ! command -v setpriv >/dev/null 2>&1; then
    sag "setpriv fehlt im Image - der Bot laeuft als root weiter, statt gar nicht zu starten."
    starte_als_root
fi

if ! id phobos >/dev/null 2>&1; then
    sag "Benutzer 'phobos' fehlt im Image - der Bot laeuft als root weiter."
    starte_als_root
fi

# ── Die Nummern angleichen ───────────────────────────────────────────────────
# Wessen Dateien auf dem Wirt einer anderen Nummer gehoeren, setzt PUID/PGID und
# bekommt genau die. -o erlaubt doppelt vergebene Nummern; das ist hier egal, im
# Container gibt es ohnehin nur diesen einen Benutzer.
if [ "$(id -g phobos 2>/dev/null)" != "$PGID" ]; then
    groupmod -o -g "$PGID" phobos 2>/dev/null || sag "Gruppennummer liess sich nicht auf $PGID setzen"
fi
if [ "$(id -u phobos 2>/dev/null)" != "$PUID" ]; then
    usermod -o -u "$PUID" -g "$PGID" phobos 2>/dev/null || sag "Benutzernummer liess sich nicht auf $PUID setzen"
fi

# ── Besitzrechte geraderuecken ───────────────────────────────────────────────
# Bei jedem Start, nicht nur beim ersten. Grund: auf dem Server wird per SSH als root
# im Repo gearbeitet (git pull, eine Datei schnell editieren) - danach stehen dort
# wieder root-eigene Dateien, und das naechste Update ueber das Dashboard scheitert.
#
# find statt "chown -R": angefasst wird nur, was tatsaechlich falsch steht. Ueber das
# Repo laufen sonst bei jedem Start ein paar tausend Dateien (android/ allein ist
# dreistellig in MB), und ein chown auf alles schreibt jedes Mal jede Inode neu.
# -h wegen symbolischer Verweise; Fehler werden geschluckt, weil ein einzelner nicht
# aenderbarer Eintrag den Start nicht verhindern darf - ob es am Ende gereicht hat,
# entscheidet die Probe weiter unten, nicht der Rueckgabewert von chown.
rueck() {
    [ -e "$1" ] || return 0
    find "$1" \( ! -user "$PUID" -o ! -group "$PGID" \) \
        -exec chown -h "$PUID:$PGID" {} + 2>/dev/null
}

for ordner in /app /app/data /home/phobos; do
    [ -d "$ordner" ] && rueck "$ordner"
done

# /repo ist der Sonderfall, und zwar ein teuer gelernter: auf einem Server mit mehreren
# Instanzen liegen im selben Verzeichnis auch die Datenordner der ANDEREN Installationen
# (data-<name>/ - alles, was git gar nicht kennt). Ein "alles unter
# /repo"-Durchlauf hat die am 17.11.2026 mit umgeschrieben. Kaputt ging dabei nichts,
# weil jene Container als root laufen und root an Dateien von 1000 trotzdem herankommt -
# aber fremde Dateien gehen diesen Bot nichts an.
#
# Angefasst wird deshalb nur, was der Bot wirklich braucht: .git (dort schreibt das
# Update), das Repo-Verzeichnis selbst (damit neue Dateien angelegt werden koennen) und
# die obersten Eintraege, die git kennt. Was git nicht kennt, bleibt unberuehrt.
if [ -d /repo/.git ]; then
    chown -h "$PUID:$PGID" /repo 2>/dev/null
    rueck /repo/.git
    for eintrag in $(git -C /repo ls-files 2>/dev/null | cut -d/ -f1 | sort -u); do
        rueck "/repo/$eintrag"
    done
fi

# ── Probe: geht das ueberhaupt gut? ──────────────────────────────────────────
# Erst wird geprueft, ob der Rechtewechsel an sich klappt (fehlt CAP_SETUID, weil jemand
# cap_drop gesetzt hat, ohne SETUID zurueckzugeben, scheitert er hier - und zwar
# folgenlos). Danach, ob der Bot als dieser Benutzer das Datenverzeichnis wirklich
# beschreiben kann. Ein Bot, der startet und dann an jeder Datenbankschreiboperation
# scheitert, ist schlimmer als einer, der wie bisher laeuft: er sieht gesund aus.
probe() {
    setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@" >/dev/null 2>&1
}

if ! probe true; then
    sag "Rechtewechsel auf uid=$PUID nicht moeglich (fehlt SETUID/SETGID?) - der Bot"
    sag "laeuft als root weiter. Nachsehen: cap_add in der compose-Datei."
    starte_als_root
fi

mkdir -p /app/data 2>/dev/null
schreibprobe="/app/data/.start-probe"
if ! probe sh -c "touch '$schreibprobe' && rm -f '$schreibprobe'"; then
    sag "Als uid=$PUID laesst sich /app/data nicht beschreiben - der Bot laeuft als root"
    sag "weiter, damit nichts stehenbleibt. Ursache ist fast immer ein Dateisystem, auf"
    sag "dem chown nicht greift (NFS, Docker Desktop, exFAT). Abhilfe: auf dem Wirt"
    sag "einmal 'chown -R $PUID:$PGID data' ausfuehren, oder PUID/PGID auf die Nummern"
    sag "setzen, denen die Dateien dort schon gehoeren."
    starte_als_root
fi

# Das Repo ist die Kuer, nicht die Pflicht: ohne Schreibrecht laeuft der Bot voellig
# normal, nur das Update ueber das Dashboard kann nichts holen. Also nur ein Hinweis.
if [ -d /repo/.git ] && ! probe test -w /repo/.git; then
    sag "Hinweis: /repo ist fuer uid=$PUID nicht beschreibbar - das Update ueber das"
    sag "Dashboard wird scheitern. Auf dem Wirt einmal 'chown -R $PUID:$PGID .' im"
    sag "Projektverzeichnis ausfuehren."
fi

sag "gebe die Rechte ab: uid=$PUID gid=$PGID"
cd /app || exit 1
exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups python main.py
