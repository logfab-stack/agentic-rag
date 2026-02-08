/**
 * TypewriterText - A component that displays text with a typewriter animation effect
 *
 * Features:
 * - Configurable speed (characters per second)
 * - Word-by-word or character-by-character modes
 * - Markdown support via callback
 * - Smooth animation with requestAnimationFrame
 * - Completion callback for parent components
 */

import { useState, useEffect, useRef, useCallback } from 'react'

export type TypewriterMode = 'character' | 'word'

export interface TypewriterTextProps {
  /** The full text to display */
  text: string
  /** Speed in items per second (characters or words depending on mode) */
  speed?: number
  /** Whether to animate by character or word */
  mode?: TypewriterMode
  /** Called when animation completes */
  onComplete?: () => void
  /** Render function for the displayed text (e.g., for markdown rendering) */
  renderText?: (text: string) => React.ReactNode
  /** Whether to skip animation and show full text immediately */
  skipAnimation?: boolean
  /** Class name for the container */
  className?: string
}

export function TypewriterText({
  text,
  speed = 40, // characters per second (or words per second in word mode)
  mode = 'character',
  onComplete,
  renderText,
  skipAnimation = false,
  className = ''
}: TypewriterTextProps) {
  const [displayedText, setDisplayedText] = useState('')
  const [isComplete, setIsComplete] = useState(false)
  const animationRef = useRef<number | null>(null)
  const startTimeRef = useRef<number | null>(null)
  const onCompleteRef = useRef(onComplete)

  // Keep onComplete ref updated
  useEffect(() => {
    onCompleteRef.current = onComplete
  }, [onComplete])

  // Parse text into items based on mode
  const getItems = useCallback((fullText: string): string[] => {
    if (mode === 'word') {
      // Split by whitespace, preserving the whitespace
      const items: string[] = []
      let currentWord = ''
      for (let i = 0; i < fullText.length; i++) {
        const char = fullText[i]
        if (/\s/.test(char)) {
          if (currentWord) {
            items.push(currentWord)
            currentWord = ''
          }
          items.push(char)
        } else {
          currentWord += char
        }
      }
      if (currentWord) {
        items.push(currentWord)
      }
      return items
    }
    // Character mode - split into individual characters
    return fullText.split('')
  }, [mode])

  // Animation loop
  useEffect(() => {
    // If skipping or no text, show full text immediately
    if (skipAnimation || !text) {
      setDisplayedText(text)
      setIsComplete(true)
      if (text && onCompleteRef.current) {
        onCompleteRef.current()
      }
      return
    }

    // Reset state for new text
    setDisplayedText('')
    setIsComplete(false)
    startTimeRef.current = null

    const items = getItems(text)
    const totalItems = items.length
    const msPerItem = 1000 / speed

    const animate = (timestamp: number) => {
      if (startTimeRef.current === null) {
        startTimeRef.current = timestamp
      }

      const elapsed = timestamp - startTimeRef.current
      const itemsToShow = Math.min(
        Math.floor(elapsed / msPerItem) + 1,
        totalItems
      )

      // Build the text from items
      const newText = items.slice(0, itemsToShow).join('')
      setDisplayedText(newText)

      if (itemsToShow < totalItems) {
        animationRef.current = requestAnimationFrame(animate)
      } else {
        // Animation complete
        setIsComplete(true)
        if (onCompleteRef.current) {
          onCompleteRef.current()
        }
      }
    }

    animationRef.current = requestAnimationFrame(animate)

    // Cleanup
    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [text, speed, skipAnimation, getItems])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [])

  // Render the text
  const renderedContent = renderText ? renderText(displayedText) : displayedText

  return (
    <span className={className}>
      {renderedContent}
      {/* Show cursor while animating */}
      {!isComplete && (
        <span className="inline-block w-0.5 h-4 ml-0.5 bg-current animate-pulse align-text-bottom" />
      )}
    </span>
  )
}

export default TypewriterText
