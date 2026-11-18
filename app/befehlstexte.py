"""Die Slash-Befehle auf Englisch - Namen, Beschreibungen, Parameter, Auswahleinträge.

Gemeldet am 17.11.2026: Auf einem englischsprachigen Server standen deutsche Befehlsnamen
in der Liste -
und unter JEDEM Befehl eine deutsche Beschreibung, auch unter den englisch benannten.

Discord kann beides je Sprache ausliefern. Entscheidend ist dabei die Client-Sprache der
PERSON, nicht die eingestellte Sprache des Servers (`bot_lang`): ein Deutscher auf einem
englischen Server sieht weiter Deutsch, und ein Engländer auf einem deutschen Server
Englisch. Das ist mit Absicht so - die Befehlsliste gehört zur Oberfläche der Person.

Übersetzt wird gegen den deutschen Quelltext, also genau gegen das, was in den Cogs steht.
Fehlt ein Eintrag, bleibt es beim deutschen Text (statt eines leeren Feldes) - und
test_befehlssprache.py schlägt an, damit ein neuer Befehl nicht unbemerkt einsprachig
bleibt.

Nicht aufgeführt ist, was in beiden Sprachen gleich heißt (`ban`, `kick`, `member`, `Chat`).
Für die gibt der Übersetzer nichts zurück, und Discord nimmt den Standardtext.
"""

# Quelltext (deutsch, wie in den Cogs) -> Englisch
BEFEHLE_EN: dict[str, str] = {
    # ── Namen ───────────────────────────────────────────────────────────────
    # Nur diese vier sind überhaupt deutsch. Die Regeln für Befehlsnamen gelten auch für
    # Übersetzungen: klein, ohne Leerzeichen.
    "bewerten": "rate",
    "bewertungen": "ratings",
    "profil": "profile",
    "profil-loeschen": "profile-delete",

    # ── Parameter ───────────────────────────────────────────────────────────
    "grund": "reason",
    "sterne": "stars",

    # ── Beschreibungen ──────────────────────────────────────────────────────
    "Alle Reaction Roles anzeigen": "List all reaction roles",
    "Alle Verwarnungen eines Mitglieds löschen": "Clear all warnings of a member",
    "Alle eigenen Commands anzeigen": "List all custom commands",
    "Das Profil einer Person ansehen": "View someone's profile",
    "Dein Profil vollständig löschen": "Delete your profile completely",
    "Dein eigenes Profil ansehen": "View your own profile",
    "Deine Bio eintragen oder ändern": "Write or change your bio",
    "Deine Kinks eintragen oder ändern (18+)": "Write or change your kinks (18+)",
    "Deine Limits eintragen oder ändern (18+)": "Write or change your limits (18+)",
    "Deine Triggers eintragen oder ändern (18+)": "Write or change your triggers (18+)",
    "Deinen Rang und XP anzeigen": "Show your rank and XP",
    "Dieses Ticket schließen": "Close this ticket",
    "Eigene VRChat-Verknüpfung entfernen": "Remove your own VRChat link",
    "Eigenen Command erstellen": "Create a custom command",
    "Eigenen Command löschen": "Delete a custom command",
    "Ein Mitglied bannen": "Ban a member",
    "Ein Mitglied kicken": "Kick a member",
    "Einen Eintrag aus der Bewertungsliste mit Sternen bewerten":
        "Give an entry from the rating list a star rating",
    "Giveaway neu auslosen": "Draw a giveaway again",
    "Giveaway sofort beenden": "End a giveaway right away",
    "Giveaway starten": "Start a giveaway",
    "Mitglied für X Minuten timen": "Time a member out for X minutes",
    "Mitglied verwarnen": "Warn a member",
    "Nachrichten löschen": "Delete messages",
    "Postet die aktuelle Bewertungsliste (mit Bewerten-Menü)":
        "Posts the current rating list (with a rating menu)",
    "Reaction Role entfernen": "Remove a reaction role",
    "Reaction Role hinzufügen": "Add a reaction role",
    "Startet den verknüpften Gameserver": "Starts the linked game server",
    "Startet den verknüpften Gameserver neu": "Restarts the linked game server",
    "Stoppt den verknüpften Gameserver": "Stops the linked game server",
    "Top 10 nach Chat-XP": "Top 10 by chat XP",
    "Umfrage erstellen": "Create a poll",
    "Umfrage vorzeitig beenden": "End a poll early",
    "User anhand ID entbannen": "Unban a user by their ID",
    "VRChat-Konto verknüpfen": "Link your VRChat account",
    "Verknüpften VRChat-Namen eines Mitglieds anzeigen":
        "Show the linked VRChat name of a member",
    "Verwarnungen eines Mitglieds": "Warnings of a member",
    "XP eines Mitglieds setzen (Admin)": "Set a member's XP (admin)",
    "Zeigt ob der verknüpfte Gameserver online ist":
        "Shows whether the linked game server is online",

    # ── Texte an Parametern ─────────────────────────────────────────────────
    "1 (schlecht) bis 5 (super)": "1 (bad) to 5 (great)",
    "Map/Seite/Spiel/...": "Map/site/game/...",
    "Name des Spiels (nur nötig wenn mehrere verknüpft sind)":
        "Name of the game (only needed when several are linked)",
    "Warum wird geschlossen? Steht später in der Mitschrift.":
        "Why is it being closed? Appears in the transcript later.",
    "Wessen Profil? Ohne Angabe dein eigenes.": "Whose profile? Your own if left empty.",
    "chat oder voice": "chat or voice",
}


def befehl_en(text: str) -> str | None:
    """Der englische Text, oder None - dann bleibt der deutsche stehen."""
    return BEFEHLE_EN.get(text)
