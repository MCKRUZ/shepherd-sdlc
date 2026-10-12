import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { FIRST_OPEN_MAX, MIN_HEIGHT, MIN_WIDTH, ZOOM_MAX, firstOpenBounds, fitSavedBounds, readSavedBounds, writeSavedBounds, zoomFor } from '../electron/main/windowBounds'

const laptop = { x: 0, y: 25, width: 1440, height: 875 }
const big = { x: 0, y: 0, width: 2560, height: 1415 }

describe('window bounds', () => {
  it('first open fits the work area with a margin, up to the ceiling, never under the floor', () => {
    expect(firstOpenBounds(big)).toMatchObject({ width: FIRST_OPEN_MAX.width, height: FIRST_OPEN_MAX.height })
    const onLaptop = firstOpenBounds(laptop)
    expect(onLaptop.width).toBe(1440 - 48)
    expect(onLaptop.height).toBe(875 - 48)
    const tiny = firstOpenBounds({ x: 0, y: 0, width: 1024, height: 700 })
    expect(tiny.width).toBe(MIN_WIDTH)
    expect(tiny.height).toBe(MIN_HEIGHT)
    // centred on the area it fits
    const b = firstOpenBounds(big)
    expect(b.x).toBe(Math.round((2560 - b.width) / 2))
  })

  it('a remembered rect is restored only when it still lands on a connected display', () => {
    expect(fitSavedBounds({ x: 100, y: 100, width: 1500, height: 900 }, [big])).toEqual({ x: 100, y: 100, width: 1500, height: 900 })
    // unplugged second display to the right
    expect(fitSavedBounds({ x: 3000, y: 100, width: 1500, height: 900 }, [big])).toBeNull()
    // too small a rect is lifted to the floor
    expect(fitSavedBounds({ x: 0, y: 0, width: 600, height: 400 }, [big])).toMatchObject({ width: MIN_WIDTH, height: MIN_HEIGHT })
    expect(fitSavedBounds(null, [big])).toBeNull()
    expect(fitSavedBounds({ x: 'a' }, [big])).toBeNull()
  })

  it('rendering scale: 1 at or under 1440, linear to 1.3 at 2560, capped, never under 1', () => {
    expect(zoomFor(1280)).toBe(1)
    expect(zoomFor(1440)).toBe(1)
    expect(zoomFor(2000)).toBe(1.15)
    expect(zoomFor(2560)).toBe(ZOOM_MAX)
    expect(zoomFor(5120)).toBe(ZOOM_MAX)
    expect(zoomFor(Number.NaN)).toBe(1)
  })

  describe('the file', () => {
    let dir = ''
    afterEach(() => { if (dir) rmSync(dir, { recursive: true, force: true, maxRetries: 5 }) })
    it('round-trips and reads null when absent or corrupt', () => {
      dir = mkdtempSync(join(tmpdir(), 'shepherd-bounds-'))
      expect(readSavedBounds(dir)).toBeNull()
      writeSavedBounds(dir, { x: 1, y: 2, width: 1300, height: 800 })
      expect(readSavedBounds(dir)).toEqual({ x: 1, y: 2, width: 1300, height: 800 })
    })
  })
})
