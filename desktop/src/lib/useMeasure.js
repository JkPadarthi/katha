import { useEffect, useState } from 'react'
import { getSetting, setSetting } from './settings.js'

// How wide the writing column is (4.0.1). Applied as <html data-measure>, so the page,
// the review and the dock all follow one CSS variable (index.css).
export const MEASURES = [
  { id: 'narrow', label: 'Narrow' },
  { id: 'medium', label: 'Medium' },
  { id: 'wide', label: 'Wide' }
]

export function useMeasure() {
  const [measure, setMeasure] = useState(() => getSetting('measure', 'medium'))
  useEffect(() => {
    document.documentElement.dataset.measure = measure
    setSetting('measure', measure)
  }, [measure])
  return [measure, setMeasure]
}
