import { useEffect, useRef, useCallback } from 'react';

/**
 * A hook that traps focus within a modal dialog for accessibility.
 * When the modal is open:
 * - Focus is moved to the first focusable element in the modal
 * - Tab/Shift+Tab cycles through focusable elements within the modal
 * - Focus cannot escape to background elements
 * - When closed, focus returns to the element that triggered the modal
 */
export function useFocusTrap(isOpen: boolean) {
  const containerRef = useRef<HTMLDivElement>(null);
  const previousActiveElementRef = useRef<HTMLElement | null>(null);

  // Get all focusable elements within the container
  const getFocusableElements = useCallback(() => {
    if (!containerRef.current) return [];

    const focusableSelectors = [
      'button:not([disabled]):not([tabindex="-1"])',
      'input:not([disabled]):not([tabindex="-1"])',
      'select:not([disabled]):not([tabindex="-1"])',
      'textarea:not([disabled]):not([tabindex="-1"])',
      'a[href]:not([tabindex="-1"])',
      '[tabindex]:not([tabindex="-1"]):not([disabled])',
    ].join(', ');

    return Array.from(
      containerRef.current.querySelectorAll<HTMLElement>(focusableSelectors)
    ).filter((el) => {
      // Filter out elements with negative tabindex or hidden elements
      return el.offsetParent !== null && el.tabIndex >= 0;
    });
  }, []);

  // Handle keydown events for focus trapping
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    if (event.key !== 'Tab') return;

    const focusableElements = getFocusableElements();
    if (focusableElements.length === 0) return;

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    // Shift+Tab on first element: move to last
    if (event.shiftKey && document.activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
    }
    // Tab on last element: move to first
    else if (!event.shiftKey && document.activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  }, [getFocusableElements]);

  useEffect(() => {
    if (isOpen) {
      // Save the currently focused element to restore later
      previousActiveElementRef.current = document.activeElement as HTMLElement;

      // Add event listener for focus trapping
      document.addEventListener('keydown', handleKeyDown);

      // Move focus to the first focusable element in the modal
      // Use setTimeout to ensure the modal is rendered before focusing
      const timeoutId = setTimeout(() => {
        const focusableElements = getFocusableElements();
        if (focusableElements.length > 0) {
          focusableElements[0].focus();
        } else if (containerRef.current) {
          // If no focusable elements, focus the container itself
          containerRef.current.focus();
        }
      }, 0);

      return () => {
        clearTimeout(timeoutId);
        document.removeEventListener('keydown', handleKeyDown);
      };
    } else {
      // When modal closes, restore focus to the previously focused element
      document.removeEventListener('keydown', handleKeyDown);
      if (previousActiveElementRef.current) {
        previousActiveElementRef.current.focus();
        previousActiveElementRef.current = null;
      }
    }
  }, [isOpen, handleKeyDown, getFocusableElements]);

  return containerRef;
}

export default useFocusTrap;
