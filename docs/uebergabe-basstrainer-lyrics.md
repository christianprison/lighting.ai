# Übergabe BassTrainer — Parts, Takte & synchrone Lyrics-Darstellung

> Ergänzung zu `uebergabe-basstrainer.md`. Hier geht es um **Parts**, die
> **Takt-Struktur mit Timing** und ein **Design-Pattern** für eine
> Lyrics-Tab-Ansicht mit Hervorhebung im Playmodus (Karaoke-/Apple-Music-Stil).

## Ehrliche Datenlage (bitte zuerst lesen)

- **Timing existiert nur für ~21 von 51 Songs** (die in der Lichtsteuerung
  „gesplittet" wurden). Für diese gibt es pro Takt eine **Startzeit** und die
  **Part-Zuordnung**.
- Für die übrigen ~30 Songs gibt es **kein** Timing — nur statische Lyrics
  (`lyrics_raw`). Dort ist nur eine nicht-synchrone Anzeige möglich.
- Lyrics liegen **pro Takt** vor (ein Takt ≈ eine kurze Textzeile/Phrase);
  nicht jeder Takt hat Text (instrumentale Takte).

Du brauchst **kein JSONB** zu parsen — es gibt dafür drei fertige Views
(read-only, public).

## Die drei Views (REST)

Header wie immer: `apikey` + `Authorization: Bearer <ANON_KEY>`.

### `song_timeline_public` — das Rückgrat für die Hervorhebung
```http
GET {URL}/rest/v1/song_timeline_public?song_id=eq.5iZfKj&order=bar_num
```
| Spalte | Typ | Bedeutung |
|---|---|---|
| `song_id` | text | |
| `bar_num` | int | Taktnummer (1-basiert, geordnet) |
| `t_start` | double | Startzeit des Takts in **Sekunden** (relativ zum playalong-Audio) |
| `t_end` | double \| null | Startzeit des nächsten Takts (= Ende der Hervorhebung); `null` beim letzten Takt → Songende/Audiodauer nehmen |
| `part_name` | text | Part, zu dem der Takt gehört („Verse 1", „Chorus 1 (nana)", …) |
| `lyrics` | text | Text dieses Takts (kann leer sein → instrumental) |
| `instrumental` | bool | true = instrumentaler Takt |

Leeres Ergebnis ⇒ Song hat kein Timing → Fallback (siehe unten).

### `song_parts_public` — die Section-Liste (Parts)
```http
GET {URL}/rest/v1/song_parts_public?song_id=eq.5iZfKj&order=start_bar
```
`{ song_id, start_bar, part_name, light_template }` — `light_template` ist
lighting-spezifisch, ignorierbar. Nützlich für eine Part-Übersicht/Sprungmarken.

### `song_lyrics_public` — statischer Fallback (alle Songs)
```http
GET {URL}/rest/v1/song_lyrics_public?song_id=eq.5iZfKj&select=lyrics_raw,total_bars
```
`lyrics_raw` enthält den vollen Text inkl. `[Part]`-Tags als Abschnittsüberschriften.

## Design-Pattern: synchron hervorgehobene Lyrics (SwiftUI/MVVM)

### Modell
```swift
struct TimelineBar: Decodable, Identifiable {
    let bar_num: Int
    let t_start: Double
    let t_end: Double?
    let part_name: String?
    let lyrics: String?
    let instrumental: Bool
    var id: Int { bar_num }
    var hasText: Bool { !(lyrics ?? "").trimmingCharacters(in: .whitespaces).isEmpty }
}
```

### ViewModel — aktiven Takt aus der Abspielzeit ableiten
Der aktive Takt ist der **letzte** mit `t_start <= currentTime`. Bei sortierter
Liste → **binäre Suche** (kein lineares Scannen pro Tick).

```swift
@MainActor final class LyricsVM: ObservableObject {
    @Published private(set) var bars: [TimelineBar] = []
    @Published private(set) var activeIndex: Int? = nil

    func update(currentTime t: Double) {
        guard !bars.isEmpty else { return }
        // upper_bound(t_start <= t) - 1
        var lo = 0, hi = bars.count
        while lo < hi { let m = (lo+hi)/2; if bars[m].t_start <= t { lo = m+1 } else { hi = m } }
        let idx = lo - 1
        if idx != activeIndex { activeIndex = idx >= 0 ? idx : nil }
    }
}
```

### Sync-Quelle — AVPlayer Periodic Time Observer
```swift
let interval = CMTime(seconds: 0.1, preferredTimescale: 600)
player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { time in
    vm.update(currentTime: time.seconds)
}
```
0.1 s reicht; die binäre Suche macht den Tick praktisch kostenlos.

### View — Part-Header + Zeilen, aktive Zeile hervorgehoben + Auto-Scroll
```swift
ScrollViewReader { proxy in
    ScrollView {
        LazyVStack(alignment: .leading, spacing: 8) {
            ForEach(Array(vm.bars.enumerated()), id: \.element.id) { i, bar in
                // Part-Überschrift, wenn ein neuer Part beginnt
                if isPartStart(i) {
                    Text(bar.part_name ?? "")
                        .font(.caption).foregroundStyle(.secondary)
                        .padding(.top, 12)
                }
                if bar.hasText {
                    Text(bar.lyrics ?? "")
                        .font(.title3)
                        .fontWeight(i == vm.activeIndex ? .bold : .regular)
                        .foregroundStyle(i == vm.activeIndex ? .primary : .secondary)
                        .opacity(i == vm.activeIndex ? 1 : 0.55)
                        .id(bar.id)
                } else if i == vm.activeIndex {
                    Text("♪").foregroundStyle(.secondary).id(bar.id)   // instrumental aktiv
                }
            }
        }.padding()
    }
    .onChange(of: vm.activeIndex) { _, idx in
        guard let idx, let id = vm.bars[safe: idx]?.id else { return }
        withAnimation(.easeInOut(duration: 0.25)) { proxy.scrollTo(id, anchor: .center) }
    }
}
```
`isPartStart(i)` = `i == 0 || bars[i].part_name != bars[i-1].part_name`.

### Tap-to-Seek (optional)
Tippt der Nutzer auf eine Zeile → `player.seek(to: CMTime(seconds: bar.t_start, …))`.
So wird die Lyrics-Liste auch zur Navigation.

## Fallback für Songs ohne Timing
1. `song_timeline_public` liefert leer → `song_lyrics_public.lyrics_raw` laden.
2. Zeilen mit `[...]` als Part-Überschrift rendern, der Rest als statische Lyrics.
3. Keine Hervorhebung/kein Auto-Scroll (kein Timing vorhanden) — ggf. dezent
   kennzeichnen („nicht synchronisiert").

## Empfehlungen / Stolpersteine
- **Eine Quelle der Wahrheit fürs Timing** ist `t_start` aus
  `song_timeline_public` — nicht selbst aus BPM rechnen.
- **Leere Lyrics-Takte** nicht als Zeile rendern (nur als aktiven `♪`-Marker,
  wenn gerade aktiv), sonst zerfasert die Anzeige.
- **`t_end == null`** nur beim letzten Takt → Songende = Audiodauer.
- **Read-only:** alles über `anon`; nie schreiben, nie `service_role`.
- Schema-Quelle: `supabase/migrations/0004_lyrics_views.sql` im lighting.ai-Repo.
