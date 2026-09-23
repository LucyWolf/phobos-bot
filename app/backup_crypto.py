"""Passwortschutz für Backup-Dateien.

Gedacht für genau einen Fall: die Datei verlässt den Server. Sie landet im Download-Ordner,
in einer Cloud, auf einem USB-Stick, in einem Chat. Dort ist sie ohne das Passwort wertlos.

Was das NICHT ist: ein Schutz für die laufende Installation. Auf dem Server liegt nichts
verschlüsselt, und das ist Absicht - der Bot braucht seine Zugangsdaten im Klartext zurück.
Wer die Maschine kontrolliert, kommt an alles. Hier geht es um die Kopie, nicht um das
Original.

Warum handgebaut statt einer Krypto-Bibliothek
----------------------------------------------
Weil dieses Projekt auch auf Android (Chaquopy) und unter Termux läuft. `cryptography` bringt
kompilierten Code mit, für den es dort kein fertiges Paket gibt; die Abhängigkeit hätte beide
Wege zerlegt. Also nur, was in jeder Python-Installation steckt.

Zusammengesetzt aus Standard-Bausteinen, keine eigenen Erfindungen:

  * scrypt leitet aus dem Passwort zwei Schlüssel ab (einen zum Verschlüsseln, einen zum
    Signieren). scrypt ist absichtlich langsam und speicherhungrig - das bremst jemanden aus,
    der Passwörter durchprobiert.
  * Die Verschlüsselung ist HMAC-SHA256 im Zählmodus: aus Schlüssel, Zufallswert und einem
    hochzählenden Zähler entsteht ein Strom, der auf die Daten gerechnet wird. HMAC gilt als
    Pseudozufallsfunktion, und genau das braucht ein Stromchiffre.
  * Danach wird über den Geheimtext signiert (encrypt-then-MAC, die Reihenfolge, die man
    nicht vertauschen darf). Ohne gültige Signatur wird gar nicht erst entschlüsselt - eine
    veränderte Datei fällt auf, statt beim Einspielen Unsinn zu erzeugen.

Ehrlich dazugesagt: eine geprüfte Bibliothek wäre mir lieber. Die Bausteine hier sind Standard,
die Zusammensetzung ist es nicht in dem Sinne, dass sie jemand für dieses Projekt geprüft hätte.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets

# Kennzeichen im Dateikopf, damit das Einspielen eine verschlüsselte Datei erkennt, ohne sie
# zu raten - und damit ein Mensch beim Hineinschauen sofort sieht, was er vor sich hat.
MAGIC = "phobos-encrypted-backup"
VERSION = 1

# scrypt-Parameter. n=2^15 mit r=8 braucht rund 32 MB und einen Sekundenbruchteil auf einem
# normalen Rechner - unbemerkt für den, der sein Passwort kennt, und teuer für den, der raten
# muss. Sie stehen mit in der Datei, damit eine später erzeugte Datei auch dann noch lesbar
# ist, wenn diese Werte hier einmal steigen.
SCRYPT_N = 1 << 15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 64          # 32 Byte zum Verschlüsseln, 32 zum Signieren


class BackupCryptoError(Exception):
    """Falsches Passwort, beschädigte oder manipulierte Datei."""


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> tuple:
    material = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                              dklen=KEY_LEN, maxmem=256 * 1024 * 1024)
    return material[:32], material[32:]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """Der Schlüsselstrom: HMAC über Zufallswert und Zähler, Block für Block."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def encrypt(data: dict, password: str) -> str:
    """Ein Backup als verschlüsselte Datei. Gibt den fertigen Dateiinhalt zurück."""
    if not password:
        raise BackupCryptoError("Ohne Passwort lässt sich nichts verschlüsseln.")
    klartext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    geheim = bytes(a ^ b for a, b in zip(klartext, _keystream(enc_key, nonce, len(klartext))))
    # Signiert wird über den GEHEIMTEXT und alles, was zum Entschlüsseln nötig ist. Wer an den
    # scrypt-Werten dreht, um die Ableitung billig zu machen, macht damit die Signatur ungültig.
    kopf = f"{VERSION}:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}".encode()
    mac = hmac.new(mac_key, kopf + salt + nonce + geheim, hashlib.sha256).hexdigest()
    return json.dumps({
        "phobos": MAGIC,
        "version": VERSION,
        "kdf": {"name": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P},
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "mac": mac,
        "data": base64.b64encode(geheim).decode(),
        "hinweis": "Verschlüsseltes Phobos-Backup. Ohne das beim Export vergebene Passwort "
                   "ist diese Datei nicht wiederherstellbar.",
    }, ensure_ascii=False, indent=2)


def is_encrypted(raw: bytes | str) -> bool:
    """Ob dieser Dateiinhalt ein verschlüsseltes Backup ist.

    Bewusst nachsichtig: alles, was sich nicht als solches ausweist, gilt als altes
    Klartext-Backup und läuft weiter durch den bisherigen Weg. Eine Datei von früher muss sich
    unverändert einspielen lassen.
    """
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        kopf = json.loads(raw)
    except Exception:
        return False
    return isinstance(kopf, dict) and kopf.get("phobos") == MAGIC


def decrypt(raw: bytes | str, password: str) -> dict:
    """Ein verschlüsseltes Backup zurückholen. Wirft BackupCryptoError mit klarem Grund."""
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        kopf = json.loads(raw)
    except Exception:
        raise BackupCryptoError("Die Datei ist unlesbar.")
    if not isinstance(kopf, dict) or kopf.get("phobos") != MAGIC:
        raise BackupCryptoError("Das ist kein verschlüsseltes Phobos-Backup.")
    if not password:
        raise BackupCryptoError("Diese Datei ist verschlüsselt — bitte das Passwort angeben.")
    try:
        kdf = kopf.get("kdf") or {}
        n, r, p = int(kdf.get("n")), int(kdf.get("r")), int(kdf.get("p"))
        salt = bytes.fromhex(kopf["salt"])
        nonce = bytes.fromhex(kopf["nonce"])
        geheim = base64.b64decode(kopf["data"])
        mac_soll = str(kopf["mac"])
        version = int(kopf.get("version", 1))
    except Exception:
        raise BackupCryptoError("Die Datei ist beschädigt.")
    # Grenzen gegen eine präparierte Datei, die den Server mit absurden Werten beschäftigt.
    if not (1 <= n <= (1 << 20)) or not (1 <= r <= 32) or not (1 <= p <= 16):
        raise BackupCryptoError("Die Datei nennt unbrauchbare Verschlüsselungs-Parameter.")

    enc_key, mac_key = _derive(password, salt, n, r, p)
    kopf_bytes = f"{version}:{n}:{r}:{p}".encode()
    mac_ist = hmac.new(mac_key, kopf_bytes + salt + nonce + geheim, hashlib.sha256).hexdigest()
    # compare_digest statt "==": ein Vergleich, der bei der ersten Abweichung abbricht, verrät
    # über seine Laufzeit, wie weit man richtig lag.
    if not hmac.compare_digest(mac_ist, mac_soll):
        raise BackupCryptoError("Falsches Passwort — oder die Datei wurde verändert.")

    klartext = bytes(a ^ b for a, b in zip(geheim, _keystream(enc_key, nonce, len(geheim))))
    try:
        daten = json.loads(klartext.decode("utf-8"))
    except Exception:
        raise BackupCryptoError("Die Datei ließ sich nicht lesen.")
    if not isinstance(daten, dict):
        raise BackupCryptoError("Die Datei enthält kein Backup.")
    return daten
