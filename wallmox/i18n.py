"""Screen text. Add a language by copying the "en" block."""

STRINGS = {
    "en": {
        "cpu": "CPU", "ram": "RAM", "storage": "Storage", "guests": "Guests",
        "running": "running", "stopped": "stopped", "of": "of",
        "cores": "cores", "load": "Load", "up": "up",
        "offline": "Node is offline",
        "waiting": "Waiting for the first data from Proxmox",
        "lost": "Proxmox is not answering",
        "last_data": "Showing data from {age} ago",
        "no_storage": "No active storage",
        "no_guests": "No VMs or containers",
        "more": "+{n} more",
        "connection_lost": "Connection to Wallmox lost, retrying",
        "last_hour": "last {min} min",
        "days": "Sun Mon Tue Wed Thu Fri Sat",
    },
    "sr": {
        "cpu": "CPU", "ram": "RAM", "storage": "Skladište", "guests": "Gosti",
        "running": "radi", "stopped": "zaustavljeno", "of": "od",
        "cores": "jezgara", "load": "Opterećenje", "up": "radi",
        "offline": "Node nije dostupan",
        "waiting": "Čekam prve podatke sa Proxmox-a",
        "lost": "Proxmox ne odgovara",
        "last_data": "Prikazani su podaci stari {age}",
        "no_storage": "Nema aktivnog skladišta",
        "no_guests": "Nema VM-ova ni kontejnera",
        "more": "još {n}",
        "connection_lost": "Veza sa Wallmox-om je prekinuta, pokušavam ponovo",
        "last_hour": "poslednjih {min} min",
        "days": "ned pon uto sre čet pet sub",
    },
}


def strings(lang: str) -> dict:
    return {**STRINGS["en"], **STRINGS.get(lang, {})}
