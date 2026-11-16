/**
 * Lightweight typed event emitter with wildcard support.
 * @module EventEmitter
 */
export class EventEmitter {
  /** @type {Map<string, Set<Function>>} */
  #listeners = new Map();

  /**
   * Subscribe to an event.
   * @param {string} event - Event name, or '*' for all events.
   * @param {Function} fn - Callback receiving (...args).
   * @returns {() => void} Unsubscribe function.
   */
  on(event, fn) {
    if (!this.#listeners.has(event)) {
      this.#listeners.set(event, new Set());
    }
    this.#listeners.get(event).add(fn);
    return () => this.off(event, fn);
  }

  /**
   * Subscribe to an event once.
   * @param {string} event
   * @param {Function} fn
   * @returns {() => void}
   */
  once(event, fn) {
    const wrapper = (...args) => {
      this.off(event, wrapper);
      fn(...args);
    };
    wrapper._original = fn;
    return this.on(event, wrapper);
  }

  /**
   * Unsubscribe from an event.
   * @param {string} event
   * @param {Function} fn
   */
  off(event, fn) {
    const set = this.#listeners.get(event);
    if (!set) return;
    set.delete(fn);
    // Also remove `once` wrappers
    for (const listener of set) {
      if (listener._original === fn) {
        set.delete(listener);
      }
    }
    if (set.size === 0) this.#listeners.delete(event);
  }

  /**
   * Emit an event.
   * @param {string} event
   * @param  {...any} args
   */
  emit(event, ...args) {
    const set = this.#listeners.get(event);
    if (set) {
      for (const fn of set) fn(...args);
    }
    // Wildcard listeners
    const wildcard = this.#listeners.get('*');
    if (wildcard) {
      for (const fn of wildcard) fn(event, ...args);
    }
  }

  /** Remove all listeners, optionally for a specific event. */
  removeAllListeners(event) {
    if (event) {
      this.#listeners.delete(event);
    } else {
      this.#listeners.clear();
    }
  }

  /** Number of listeners for an event. */
  listenerCount(event) {
    return this.#listeners.get(event)?.size ?? 0;
  }
}
