/**
 * WelcomeModal - Welcome/tutorial modal shown on first launch
 * Explains how to use the application to new users
 */

import { X, Upload, MessageSquare, FileText, Database, Search, Settings } from 'lucide-react';
import { useEffect, useRef } from 'react';

interface WelcomeModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const FEATURES = [
  {
    icon: Upload,
    title: 'Upload Documents',
    description: 'Support for PDF, TXT, Word, Markdown, CSV, Excel, and JSON files.',
  },
  {
    icon: MessageSquare,
    title: 'Chat with AI',
    description: 'Ask questions about your documents in natural language.',
  },
  {
    icon: Search,
    title: 'Smart Search',
    description: 'Semantic search finds relevant information across all text documents.',
  },
  {
    icon: Database,
    title: 'Data Analysis',
    description: 'Query tabular data (CSV, Excel) with automatic SQL generation.',
  },
];

export function WelcomeModal({ isOpen, onClose }: WelcomeModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  // Focus trap: keep focus inside modal
  useEffect(() => {
    if (!isOpen) return;

    // Focus the close button when modal opens
    closeButtonRef.current?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      // Handle Escape key
      if (e.key === 'Escape') {
        handleGetStarted();
        return;
      }

      // Handle Tab key for focus trapping
      if (e.key === 'Tab') {
        if (!modalRef.current) return;

        const focusableElements = modalRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          // Shift + Tab: moving backwards
          if (document.activeElement === firstElement) {
            e.preventDefault();
            lastElement?.focus();
          }
        } else {
          // Tab: moving forwards
          if (document.activeElement === lastElement) {
            e.preventDefault();
            firstElement?.focus();
          }
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  if (!isOpen) {
    return null;
  }

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleGetStarted = () => {
    // Mark as seen in localStorage
    localStorage.setItem('rag-welcome-seen', 'true');
    onClose();
  };

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="welcome-modal-title"
    >
      <div ref={modalRef} className="bg-light-bg dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-light-border dark:border-dark-border">
          <h2 id="welcome-modal-title" className="text-lg font-semibold text-light-text dark:text-dark-text">
            Welcome to Agentic RAG System
          </h2>
          <button
            ref={closeButtonRef}
            onClick={handleGetStarted}
            className="text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text transition-colors"
            aria-label="Close welcome modal"
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Introduction */}
          <div className="text-center">
            <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4">
              <FileText className="w-8 h-8 text-primary" />
            </div>
            <p className="text-light-text dark:text-dark-text">
              Your intelligent document assistant that helps you analyze, search, and query your documents using AI.
            </p>
          </div>

          {/* Features Grid */}
          <div className="grid grid-cols-2 gap-4">
            {FEATURES.map(({ icon: Icon, title, description }) => (
              <div
                key={title}
                className="p-4 rounded-lg bg-light-sidebar dark:bg-dark-sidebar border border-light-border dark:border-dark-border"
              >
                <div className="flex items-center gap-2 mb-2">
                  <Icon size={18} className="text-primary" />
                  <h3 className="font-medium text-sm text-light-text dark:text-dark-text">
                    {title}
                  </h3>
                </div>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                  {description}
                </p>
              </div>
            ))}
          </div>

          {/* Getting Started Tips */}
          <div className="bg-primary/5 dark:bg-primary/10 rounded-lg p-4">
            <h3 className="font-medium text-sm text-light-text dark:text-dark-text mb-2 flex items-center gap-2">
              <Settings size={16} className="text-primary" />
              Quick Start
            </h3>
            <ol className="text-xs text-light-text-secondary dark:text-dark-text-secondary space-y-1 list-decimal list-inside">
              <li>Configure your OpenAI API key in Settings (bottom of sidebar)</li>
              <li>Upload your first document using the "Upload Document" button</li>
              <li>Start chatting to analyze your documents!</li>
            </ol>
          </div>

          {/* Action Button */}
          <div className="flex justify-center pt-2">
            <button
              onClick={handleGetStarted}
              className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors font-medium"
            >
              Get Started
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default WelcomeModal;
