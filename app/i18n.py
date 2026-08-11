TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        # Sidebar – Einstellungen
        "nav_settings":       "Einstellungen",
        "nav_tokens":         "Tokens",
        "nav_users":          "Benutzer",
        "nav_roles":          "Rollen",
        "nav_bot_info":       "Bot-Info",
        "nav_servers":        "Server",
        "nav_twitch_api":     "Streaming-API",
        "nav_smtp":           "E-Mail / SMTP",
        "nav_updates":        "Updates",
        "nav_timezone":       "Zeitzone",
        # Sidebar – Server
        "nav_config":         "Konfiguration",
        "nav_leveling":       "Leveling",
        "nav_rr":             "Reaction Roles",
        "nav_commands":       "Commands",
        "nav_tickets":        "Tickets",
        "nav_giveaways":      "Giveaways",
        "nav_warnings":       "Warnungen",
        "nav_twitch":         "Streaming",
        "nav_freestuff":      "Free Stuff",
        "nav_log":            "Log",
        "nav_bot_design":     "Bot-Design",
        "nav_dashboard":      "Dashboard",
        # Buttons
        "btn_save":           "💾 Speichern",
        "btn_add":            "➕ Hinzufügen",
        "btn_delete":         "Löschen",
        "btn_cancel":         "Abbrechen",
        "btn_edit":           "Bearbeiten",
        "btn_send":           "📤 Senden",
        # Common labels
        "label_name":         "Name",
        "label_channel":      "Kanal",
        "label_message":      "Nachricht",
        "label_password":     "Passwort",
        "label_email":        "E-Mail",
        "label_role":         "Rolle",
        "label_token":        "Token",
        "saved_ok":           "Gespeichert.",
        "no_access":          "Du hast keinen Zugriff auf diesen Bereich.",
        # Tokens
        "tokens_add":         "Token hinzufügen",
        "tokens_label":       "Bezeichnung",
        "tokens_online":      "🟢 Online",
        "tokens_enabled":     "⚙️ Aktiviert",
        "tokens_disabled":    "⏸ Deaktiviert",
        "tokens_restart_hint":"Neustart erforderlich um ihn zu aktivieren.",
        # Settings
        "tz_hint":            "Wie Zeitangaben im Dashboard angezeigt werden. Aktuell:",
        # Users
        "users_create":       "Nutzer anlegen",
        "users_username":     "Benutzername",
        # Roles
        "roles_create":       "Rolle erstellen",
        "roles_color":        "Farbe",
        "roles_perms":        "Berechtigungen",
        # Lang toggle label (shows the OTHER language to switch to)
        "lang_switch":        "🇬🇧 EN",
    },
    "en": {
        # Sidebar – Settings
        "nav_settings":       "Settings",
        "nav_tokens":         "Tokens",
        "nav_users":          "Users",
        "nav_roles":          "Roles",
        "nav_bot_info":       "Bot Info",
        "nav_servers":        "Servers",
        "nav_twitch_api":     "Streaming API",
        "nav_smtp":           "E-Mail / SMTP",
        "nav_updates":        "Updates",
        "nav_timezone":       "Timezone",
        # Sidebar – Server
        "nav_config":         "Configuration",
        "nav_leveling":       "Leveling",
        "nav_rr":             "Reaction Roles",
        "nav_commands":       "Commands",
        "nav_tickets":        "Tickets",
        "nav_giveaways":      "Giveaways",
        "nav_warnings":       "Warnings",
        "nav_twitch":         "Streaming",
        "nav_freestuff":      "Free Stuff",
        "nav_log":            "Log",
        "nav_bot_design":     "Bot Design",
        "nav_dashboard":      "Dashboard",
        # Buttons
        "btn_save":           "💾 Save",
        "btn_add":            "➕ Add",
        "btn_delete":         "Delete",
        "btn_cancel":         "Cancel",
        "btn_edit":           "Edit",
        "btn_send":           "📤 Send",
        # Common labels
        "label_name":         "Name",
        "label_channel":      "Channel",
        "label_message":      "Message",
        "label_password":     "Password",
        "label_email":        "E-Mail",
        "label_role":         "Role",
        "label_token":        "Token",
        "saved_ok":           "Saved.",
        "no_access":          "You don't have access to this area.",
        # Tokens
        "tokens_add":         "Add token",
        "tokens_label":       "Label",
        "tokens_online":      "🟢 Online",
        "tokens_enabled":     "⚙️ Enabled",
        "tokens_disabled":    "⏸ Disabled",
        "tokens_restart_hint":"Restart required to activate.",
        # Settings
        "tz_hint":            "How timestamps are displayed in the dashboard. Current:",
        # Users
        "users_create":       "Create user",
        "users_username":     "Username",
        # Roles
        "roles_create":       "Create role",
        "roles_color":        "Color",
        "roles_perms":        "Permissions",
        # Lang toggle label
        "lang_switch":        "🇩🇪 DE",
    },
}


def get_tr(lang: str) -> dict[str, str]:
    base = TRANSLATIONS["de"]
    override = TRANSLATIONS.get(lang, {})
    return {**base, **override}
