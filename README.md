# Buy Me a Pie für Home Assistant

Inoffizielle Home-Assistant-Integration für die Einkaufslisten-App [Buy Me a Pie](https://buymeapie.com).
Jede Liste deines Kontos erscheint als **To-do-Liste** in Home Assistant. Du kannst dort
Artikel hinzufügen, abhaken, umbenennen und löschen. Das funktioniert auch per Sprachassistent
(„Füge Milch zur Einkaufsliste hinzu“).

> ⚠️ Die Integration nutzt die nicht dokumentierte API der Web-App (`api.buymeapie.com`).
> Sie ist nicht mit dem Hersteller verbunden und kann bei Änderungen der API jederzeit ausfallen.

## Funktionen

- Eine To-do-Entität pro Liste, z. B. `todo.einkaufsliste`, jeweils als eigenes Gerät
- Neue Listen erscheinen automatisch
- Artikel hinzufügen: Der Name wird zum Artikel, die Beschreibung zur Menge (z. B. „2 l“)
- Abhaken bzw. zurücksetzen entspricht „gekauft“ in der App
- Wird ein Artikel hinzugefügt, der schon als gekauft in der Liste steht, wird er wieder aktiviert.
  So entstehen keine Dubletten, genau wie in der App.
- Attribute: `list_id`, `purchased_items`, `shared_with` (Anzahl der Personen, mit denen die Liste geteilt ist)
- Ändert sich die PIN, fragt Home Assistant automatisch nach der neuen.

## Installation

### HACS (benutzerdefiniertes Repository)

1. HACS → ⋮ → *Benutzerdefinierte Repositories*
2. Repository `https://github.com/m-bck/hacs_bmap` als Typ **Integration** hinzufügen
3. „Buy Me a Pie“ installieren und Home Assistant neu starten

### Manuell

Den Ordner `custom_components/buymeapie` nach `<config>/custom_components/` kopieren und
Home Assistant neu starten.

## Einrichtung

*Einstellungen → Geräte & Dienste → Integration hinzufügen → Buy Me a Pie*.
Dort Login und 4-stellige PIN eingeben (zu finden in der App unter *Einstellungen → Konto*).

### Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| Abfrageintervall | 30 s | Wie oft nach Änderungen gefragt wird (mindestens 20 s). Die API hat keinen Push. |
| Gekaufte Artikel anzeigen | an | Zeigt gekaufte Artikel als erledigt an. |

> Hinweis: Mit „Erledigte entfernen“ in Home Assistant werden die gekauften Artikel auch in
> Buy Me a Pie **gelöscht** und fehlen dann im Verlauf der Liste. Wer das vermeiden möchte,
> schaltet „Gekaufte Artikel anzeigen“ aus.

## Beispiele

```yaml
# Artikel mit Menge hinzufügen
action: todo.add_item
target:
  entity_id: todo.einkaufsliste
data:
  item: Milch
  description: "2"
```

```yaml
# Benachrichtigung, sobald etwas auf der Liste steht und ich beim Supermarkt bin
triggers:
  - trigger: zone
    entity_id: person.ich
    zone: zone.supermarkt
    event: enter
conditions:
  - condition: numeric_state
    entity_id: todo.einkaufsliste
    above: 0
actions:
  - action: notify.mobile_app_mein_handy
    data:
      message: "{{ states('todo.einkaufsliste') }} Artikel auf der Einkaufsliste"
```

## Technik

- Anmeldung: HTTP Basic Auth (`login:pin`), Prüfung über `GET /bauth`
- `GET /lists` liefert die Listen.
- Beim ersten Mal wird die ganze Liste über `GET /lists/{id}/items` geladen.
  Danach werden nur noch Änderungen über `GET /lists/{id}/changed_items/{timestamp}` abgefragt.
  Wichtig bei alten Listen: Der Server liefert auch gelöschte Artikel mit, das können mehrere hundert KB sein.
- Schreiben: `POST /lists/{id}/items`, `PUT /lists/{id}/items/{item}`, `DELETE /lists/{id}/items/{item}`
- Antwortet der Server mit 423 (gesperrt), wird nach 1 s erneut versucht. Bei 401 bzw. 422 startet die erneute Anmeldung.

## Entwicklung

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

## Einschränkungen

- Die Reihenfolge der Artikel kann nicht geändert werden, weil die API kein Feld dafür hat.
- Kategorien (`group_id`) werden noch nicht angezeigt.
- Listen werden noch nicht in Home Assistant angelegt, umbenannt oder gelöscht.
