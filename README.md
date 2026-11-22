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
- **Kategorien:** Offene Artikel sind nach Kategorie sortiert, in derselben Reihenfolge wie in der App.
  Die Kategorie steht in der Beschreibung, z. B. „2 · 🥦 Obst & Gemüse“.
- **Automatische Kategorisierung:** Neue Artikel aus Home Assistant bekommen automatisch eine passende Farbe.
- **Rezepte:** Rezepte in Home Assistant hinterlegen und per Button, NFC-Tag, Automation oder Sprachbefehl
  auf die Einkaufsliste setzen. Doppelte Artikel werden zusammengeführt, Mengen auf Portionen umgerechnet,
  und vorhandene Zutaten lassen sich weglassen („Lasagne, aber Tomaten hab ich noch“).
- Attribute: `list_id`, `purchased_items`, `shared_with` (Anzahl der Personen, mit denen die Liste geteilt ist)
  und `categories` (offene Artikel je Kategorie mit Name und Farbe, z. B. für ein Dashboard)
- Ändert sich die PIN, fragt Home Assistant automatisch nach der neuen.

## Installation

Voraussetzung: Home Assistant 2026.10 oder neuer (getestet mit 2026.10.4).

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
| Neue Artikel automatisch kategorisieren | an | Siehe [Kategorien](#kategorien). |
| Kategorie in der Beschreibung anzeigen | an | Die Menge bleibt editierbar, der Kategoriename wird beim Speichern ignoriert. |
| Liste für Rezepte | erste Liste | Auf diese Liste kommen Rezepte von Buttons, NFC-Tags und Sprachbefehlen. |
| Kategorien benennen | siehe unten | Zweiter Schritt der Optionen: ein Name je Farbe. |

> Hinweis: Mit „Erledigte entfernen“ in Home Assistant werden die gekauften Artikel auch in
> Buy Me a Pie **gelöscht** und fehlen dann im Verlauf der Liste. Wer das vermeiden möchte,
> schaltet „Gekaufte Artikel anzeigen“ aus.

## Kategorien

Buy Me a Pie kennt nur **Farben** (`group_id` 0–28), keine Namen. Die Farbe hängt am Artikelnamen
und gilt in allen Listen. Die Integration bringt einen Vorschlag mit, wofür jede Farbe steht.
Er wurde aus einem echten Einkaufsverlauf mit rund 1.800 Artikeln abgeleitet: Jede Farbe steht für einen Bereich im Supermarkt,
und die App zeigt sie in der Reihenfolge eines Einkaufsrundgangs.

| Reihenfolge | Farbe | Nr. | Vorschlag | Typische Artikel |
|---|---|---|---|---|
| 1 | Türkis | 7 | 🧀 Kühlregal & Molkerei | Milch, Butter, Eier, Käse, Joghurt, Tortellini, Feinkostsalate |
| 2 | Grün | 6 | 🥦 Obst & Gemüse | Bananen, Paprika, Tomaten, Äpfel, frische Kräuter |
| 3 | Pink | 5 | 🥓 Fleisch & Wurst | Wurst, Hackfleisch, Hähnchen, Bacon, Schinken |
| 4 | Orange | 4 | 🥫 Vorrat, Brot & Getränke | Brot, Nudeln, Mehl, Konserven, Saucen, Gewürze, Säfte |
| 5 | Rot | 3 | 🥩 Frischetheke | Schweinefilet, Lachsschinken, Lyoner, Fleischsalat |
| 6 | Lila | 2 | 🥐 Bäckerei | Brötchen, Croissants |
| 7 | Blau | 1 | 🧊 Tiefkühl | Lachs, Fischstäbchen, Pizza, Pommes, TK-Gemüse, Eis |
| 8 | Grau / ohne | 0 | 🧻 Drogerie, Haushalt & Sonstiges | Klopapier, Spültabs, Wattepads, Backpapier |

Die Namen lassen sich in den Optionen ändern. Die Farben 8–28 heißen „Farbe N“.

### Automatische Kategorisierung

Legt Home Assistant einen Artikel neu an, speichert die Integration dessen Kategorie wie die App im
Artikelverlauf. Die Kategorie wird so bestimmt:

1. **Bekannter Artikel:** Die Farbe aus dem eigenen Verlauf wird übernommen.
2. **Schlagwörter:** Eine eingebaute Liste mit deutschen Supermarkt-Begriffen. Zusammengesetzte Wörter werden über
   ihr Ende erkannt: „Hafermilch“ → *milch*, „Rinderhackfleisch“ → *hack*. Der längste Treffer gewinnt,
   also „Kokosmilch“ → Vorrat und „Fleischsalat“ → Frischetheke. „TK …“ ist immer Tiefkühl.
3. **Ähnliche Artikel im Verlauf:** Für Unbekanntes wird nach ähnlichen Artikeln aus dem eigenen Verlauf gesucht.
4. Sonst: ohne Farbe.

Gemessen am echten Verlauf trifft das Verfahren bei rund 400 regelmäßig gekauften Artikeln in etwa
**87 %** der Fälle die Farbe, die von Hand vergeben wurde. Gemessen wurde, indem jeder Artikel so behandelt wurde,
als käme er neu dazu. Die meisten Abweichungen sind persönliche Eigenheiten, z. B. Sahne an der Theke.
Bereits kategorisierte Artikel werden nie überschrieben.

### Aktionen

```yaml
# Kategorie eines Artikels setzen (Name, Teil des Namens oder Farbnummer)
action: buymeapie.set_category
target:
  entity_id: todo.einkaufsliste
data:
  item: Hafermilch
  category: Kühlregal
```

```yaml
# Nachsehen, welche Kategorie die Integration wählen würde und warum
action: buymeapie.suggest_category
target:
  entity_id: todo.einkaufsliste
data:
  item: Bio Ziegenfrischkäse
# Antwort: category_id: 7, category: "🧀 Kühlregal & Molkerei", source: keyword, reason: kase
```

## Rezepte

### Rezept anlegen

*Einstellungen → Geräte & Dienste → Buy Me a Pie → ⋮ bzw. „+ Rezept hinzufügen“*. Jedes Rezept ist ein
eigener Untereintrag und lässt sich dort später bearbeiten oder löschen.

| Feld | Beispiel |
|---|---|
| Name | Lasagne |
| Andere Namen | Nudelauflauf, Lasagna (für Sprachbefehle) |
| Portionen | 4 |
| Zutaten | eine pro Zeile, Menge vorne (siehe unten) |

```text
500 g Hackfleisch
2 Dosen stückige Tomaten
1 Zwiebel
2 Zehen Knoblauch
250 ml Milch
Lasagneplatten
Parmesan | 100 g
# Gewürze habe ich immer da
```

- **Menge vorne:** Zahl (auch `1/2`, `½`, `1,5` oder `3-4`), optional mit Einheit
  (`g`, `kg`, `ml`, `l`, `EL`, `TL`, `Dose`, `Bund`, `Zehe`, `Becher`, `Packung` …). Der Rest der Zeile ist der Artikelname.
- **Alternative Schreibweise:** `Name | Menge`
- **Umrechnen auf Portionen:** Gewichte und Volumen werden gerundet, z. B. 750 g, 375 ml. Gezählte Zutaten
  wie Eier, Dosen oder Zwiebeln werden aufgerundet, es gibt also keine „4½ Eier“.
- **Kommentare:** Zeilen mit `#` werden ignoriert.

### Was beim Übernehmen passiert

| Zutat ist … | Ergebnis |
|---|---|
| nicht auf der Liste | wird hinzugefügt (inkl. automatischer Kategorie) |
| als gekauft auf der Liste | wird wieder aktiviert |
| schon offen auf der Liste | bleibt, wie sie ist. Die Menge wird nur eingetragen, wenn bisher keine dasteht. |
| unter „ohne“ genannt | wird übersprungen. „Tomaten“ trifft „stückige Tomaten“, aber nicht „Tomatenmark“. |

Zweimal dasselbe Rezept zu übernehmen erzeugt also keine Dubletten.

### Button, NFC-Tag, Dashboard

Für jedes Rezept gibt es einen Button, z. B. `button.lasagne_auf_die_einkaufsliste`.

```yaml
# NFC-Tag am Kochbuch oder am Kühlschrank
triggers:
  - trigger: tag
    tag_id: rezept-lasagne
actions:
  - action: button.press
    target:
      entity_id: button.lasagne_auf_die_einkaufsliste
```

### Aktionen

```yaml
action: buymeapie.add_recipe
data:
  recipe: Lasagne
  portions: 6               # optional, rechnet die Mengen um
  without: [Tomaten]        # optional
  # todo_list: todo.wocheneinkauf   # optional, sonst die Liste für Rezepte
response_variable: ergebnis  # optional: added, reactivated, already_on_list, skipped, unknown_exclusions
```

```yaml
action: buymeapie.get_recipe   # ohne recipe: Liste aller Rezepte
data:
  recipe: Lasagne
  portions: 2
response_variable: rezept
```

### Sprachassistent

- **Mit KI-Assistent** (z. B. OpenAI, Anthropic, Ollama mit „Assist“-Steuerung): Die Integration stellt zwei
  Werkzeuge bereit, `buymeapie__add_recipe` und `buymeapie__get_recipe`, und nennt dem Modell die gespeicherten Rezepte.
  Damit funktionieren freie Formulierungen wie „Was brauche ich für Lasagne?“, „Setz Lasagne für 6 auf die Liste“ oder
  „Lasagne, aber Tomaten hab ich noch“.
- **Ohne KI** (Standard-Assistent): [examples/custom_sentences/de/buymeapie.yaml](examples/custom_sentences/de/buymeapie.yaml)
  nach `<config>/custom_sentences/de/` kopieren und Home Assistant neu starten. Danach funktionieren Sätze wie
  „Setz Lasagne auf die Einkaufsliste“, „Wir kochen Chili für 6 Personen“ oder „Was brauche ich für Lasagne?“.

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
- Rezepte liegen nur in Home Assistant, als Untereinträge der Integration. Buy Me a Pie selbst bekommt nur die Artikel.
- Kategorien: Der Artikelverlauf `GET /unique_items` wird alle 15 Minuten geladen. Kategorien werden mit
  `PUT /unique_items/{titel}` und `{group_id, permanent, use_count}` gesetzt.
- Antwortet der Server mit 423 (gesperrt), wird nach 1 s erneut versucht. Bei 401 bzw. 422 startet die erneute Anmeldung.

## Entwicklung

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

## Einschränkungen

- Die Reihenfolge der Artikel kann nicht geändert werden, weil die API kein Feld dafür hat.
- Beim Hinzufügen über die To-do-Oberfläche lässt sich keine Kategorie wählen. Dafür gibt es die
  automatische Kategorisierung und `buymeapie.set_category`.
- Listen werden noch nicht in Home Assistant angelegt, umbenannt oder gelöscht.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
