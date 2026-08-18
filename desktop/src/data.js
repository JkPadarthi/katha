// Mock archive for Phase 0.1 — the real one arrives with the FastAPI
// backend in 0.2. Shape mirrors the storage decision (D6): series → books
// → chapters as .md, with bible/ alongside.

export const archive = [
  {
    id: 'series-ember',
    name: 'The Ember Throne',
    books: [
      {
        id: 'book-flame',
        title: 'The First Flame',
        chapters: [
          { id: 'ch1', title: 'The Dying Ember', words: 1243 },
          { id: 'ch2', title: 'The Road to Varna', words: 1892 },
          { id: 'ch3', title: 'The Inn at Crosswater', words: 1547 },
          { id: 'ch4', title: "Kael's Bargain", words: 2110 }
        ],
        bible: [
          { id: 'b-characters', title: 'characters.md' },
          { id: 'b-places', title: 'places.md' },
          { id: 'b-timeline', title: 'timeline.md' }
        ]
      }
    ]
  }
]

export const sampleProse = `The fire in the hearth had burned low, and the inn at Crosswater had grown quiet with it. Kael sat at the long table with a cup he had long stopped drinking from, watching the smoke climb toward the beams.

The door opened.

He did not look up — not yet. Some men you know by the weight of their step, and this one walked like a man carrying a debt.

"I heard you were dead," the stranger said.

Kael turned the cup slowly. "You heard wrong."

"Then you'll be glad to know the price on your head has doubled since the spring."

Now he looked. The gold by the door caught the lamplight, and in the stranger's eyes he saw the road ahead of him — long, and dark, and already paid for.`

export const museSeed = [
  {
    role: 'user',
    text: 'Write Kael\u2019s argument with the innkeeper — his voice, tense, short sentences.'
  },
  {
    role: 'muse',
    text: 'Draft pulled from ch. 4 voice notes: Kael speaks in clipped, low-register lines; the innkeeper hemmed and hawed; Kael ended it with a question that was not a question.'
  }
]