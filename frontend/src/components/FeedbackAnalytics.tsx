/**
 * FeedbackAnalytics - Dashboard showing statistics about chunk feedback
 * Shows total counts, percentages, top chunks, and trend data
 */

import { useState, useEffect, useCallback } from 'react';
import { Loader2, ThumbsUp, ThumbsDown, BarChart3, FileText, TrendingUp, RefreshCw, AlertCircle } from 'lucide-react';
import { getFeedbackAnalytics, FeedbackAnalyticsResponse, TopChunkInfo, FeedbackTrendItem } from '../api/feedback';

interface FeedbackAnalyticsProps {
  className?: string;
}

export function FeedbackAnalytics({ className = '' }: FeedbackAnalyticsProps) {
  const [analytics, setAnalytics] = useState<FeedbackAnalyticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAnalytics = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getFeedbackAnalytics(30);
      setAnalytics(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load feedback analytics');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  if (isLoading) {
    return (
      <div className={`space-y-4 ${className}`}>
        <div className="flex items-center gap-2">
          <BarChart3 size={18} className="text-purple-500" />
          <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
            Feedback Analytics
          </h3>
        </div>
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
          <span className="ml-2 text-light-text-secondary dark:text-dark-text-secondary">
            Loading analytics...
          </span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`space-y-4 ${className}`}>
        <div className="flex items-center gap-2">
          <BarChart3 size={18} className="text-purple-500" />
          <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
            Feedback Analytics
          </h3>
        </div>
        <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg text-red-600 dark:text-red-400">
          <AlertCircle size={16} />
          <span className="text-sm">{error}</span>
          <button
            onClick={loadAnalytics}
            className="ml-auto flex items-center gap-1 text-sm hover:underline"
          >
            <RefreshCw size={14} />
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!analytics) {
    return null;
  }

  const hasData = analytics.total_feedback > 0;

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 size={18} className="text-purple-500" />
          <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
            Feedback Analytics
          </h3>
        </div>
        <button
          onClick={loadAnalytics}
          className="flex items-center gap-1 text-xs text-light-text-secondary dark:text-dark-text-secondary hover:text-primary transition-colors"
          title="Refresh analytics"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
        Track how users rate retrieved chunks to identify high and low quality content.
      </p>

      {!hasData ? (
        <div className="text-center py-6 text-light-text-secondary dark:text-dark-text-secondary">
          <BarChart3 size={32} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No feedback data yet</p>
          <p className="text-xs mt-1">
            Feedback will appear here when users rate retrieved chunks with thumbs up/down
          </p>
        </div>
      ) : (
        <>
          {/* Summary Stats */}
          <div className="grid grid-cols-3 gap-3">
            {/* Total Feedback */}
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-light-text dark:text-dark-text">
                {analytics.total_feedback}
              </div>
              <div className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                Total Feedback
              </div>
            </div>

            {/* Positive */}
            <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3 text-center">
              <div className="flex items-center justify-center gap-1">
                <ThumbsUp size={16} className="text-green-600 dark:text-green-400" />
                <span className="text-2xl font-bold text-green-600 dark:text-green-400">
                  {analytics.positive_percentage}%
                </span>
              </div>
              <div className="text-xs text-green-700 dark:text-green-300">
                Positive ({analytics.positive_count})
              </div>
            </div>

            {/* Negative */}
            <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-3 text-center">
              <div className="flex items-center justify-center gap-1">
                <ThumbsDown size={16} className="text-red-600 dark:text-red-400" />
                <span className="text-2xl font-bold text-red-600 dark:text-red-400">
                  {analytics.negative_percentage}%
                </span>
              </div>
              <div className="text-xs text-red-700 dark:text-red-300">
                Negative ({analytics.negative_count})
              </div>
            </div>
          </div>

          {/* Top Upvoted Chunks */}
          {analytics.top_upvoted_chunks.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <ThumbsUp size={14} className="text-green-600 dark:text-green-400" />
                <h4 className="text-xs font-semibold text-light-text dark:text-dark-text uppercase">
                  Top Upvoted Chunks
                </h4>
              </div>
              <div className="space-y-2">
                {analytics.top_upvoted_chunks.map((chunk, index) => (
                  <ChunkCard key={chunk.chunk_id} chunk={chunk} rank={index + 1} type="upvoted" />
                ))}
              </div>
            </div>
          )}

          {/* Top Downvoted Chunks */}
          {analytics.top_downvoted_chunks.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <ThumbsDown size={14} className="text-red-600 dark:text-red-400" />
                <h4 className="text-xs font-semibold text-light-text dark:text-dark-text uppercase">
                  Top Downvoted Chunks (Review/Delete)
                </h4>
              </div>
              <div className="space-y-2">
                {analytics.top_downvoted_chunks.map((chunk, index) => (
                  <ChunkCard key={chunk.chunk_id} chunk={chunk} rank={index + 1} type="downvoted" />
                ))}
              </div>
            </div>
          )}

          {/* Feedback Trend */}
          {analytics.feedback_trend.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <TrendingUp size={14} className="text-primary" />
                <h4 className="text-xs font-semibold text-light-text dark:text-dark-text uppercase">
                  Recent Feedback Trend (Last 30 Days)
                </h4>
              </div>
              <FeedbackTrendChart trend={analytics.feedback_trend} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ChunkCard component for displaying chunk info
interface ChunkCardProps {
  chunk: TopChunkInfo;
  rank: number;
  type: 'upvoted' | 'downvoted';
}

function ChunkCard({ chunk, rank, type }: ChunkCardProps) {
  const bgColor = type === 'upvoted'
    ? 'bg-green-50 dark:bg-green-900/10 border-green-200 dark:border-green-800'
    : 'bg-red-50 dark:bg-red-900/10 border-red-200 dark:border-red-800';

  const scoreColor = type === 'upvoted'
    ? 'text-green-600 dark:text-green-400'
    : 'text-red-600 dark:text-red-400';

  return (
    <div className={`p-2 rounded-lg border ${bgColor}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="text-xs font-mono text-light-text-secondary dark:text-dark-text-secondary">
            #{rank}
          </span>
          <FileText size={14} className="text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0" />
          <span className="text-sm font-medium text-light-text dark:text-dark-text truncate">
            {chunk.document_name || 'Unknown Document'}
          </span>
        </div>
        <div className={`flex items-center gap-1 flex-shrink-0 ${scoreColor}`}>
          {type === 'upvoted' ? <ThumbsUp size={12} /> : <ThumbsDown size={12} />}
          <span className="text-xs font-semibold">
            {type === 'upvoted' ? '+' : ''}{chunk.net_score}
          </span>
        </div>
      </div>
      {chunk.text_preview && (
        <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1 line-clamp-2">
          {chunk.text_preview}
        </p>
      )}
      <div className="flex items-center gap-3 mt-1 text-xs text-light-text-secondary dark:text-dark-text-secondary">
        <span className="flex items-center gap-1">
          <ThumbsUp size={10} className="text-green-500" />
          {chunk.positive_count}
        </span>
        <span className="flex items-center gap-1">
          <ThumbsDown size={10} className="text-red-500" />
          {chunk.negative_count}
        </span>
      </div>
    </div>
  );
}

// Simple trend chart component
interface FeedbackTrendChartProps {
  trend: FeedbackTrendItem[];
}

function FeedbackTrendChart({ trend }: FeedbackTrendChartProps) {
  if (trend.length === 0) return null;

  // Get max total for scaling
  const maxTotal = Math.max(...trend.map(t => t.total), 1);

  return (
    <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3">
      <div className="flex items-end justify-between gap-1 h-20">
        {trend.map((item, _index) => {
          const height = (item.total / maxTotal) * 100;
          const positiveHeight = item.total > 0 ? (item.positive / item.total) * height : 0;
          const negativeHeight = item.total > 0 ? (item.negative / item.total) * height : 0;

          return (
            <div
              key={item.date}
              className="flex-1 flex flex-col justify-end items-center group relative"
              title={`${item.date}: +${item.positive} / -${item.negative}`}
            >
              {/* Tooltip */}
              <div className="absolute bottom-full mb-1 hidden group-hover:block bg-dark-bg dark:bg-light-bg text-dark-text dark:text-light-text text-xs px-2 py-1 rounded shadow-lg whitespace-nowrap z-10">
                <div className="font-medium">{item.date}</div>
                <div className="flex items-center gap-2">
                  <span className="text-green-500">+{item.positive}</span>
                  <span className="text-red-500">-{item.negative}</span>
                </div>
              </div>

              {/* Bar */}
              <div className="w-full max-w-4 flex flex-col justify-end" style={{ height: '100%' }}>
                {/* Negative portion (bottom) */}
                {negativeHeight > 0 && (
                  <div
                    className="w-full bg-red-400 dark:bg-red-500 rounded-t-sm"
                    style={{ height: `${negativeHeight}%`, minHeight: negativeHeight > 0 ? '2px' : 0 }}
                  />
                )}
                {/* Positive portion (top) */}
                {positiveHeight > 0 && (
                  <div
                    className="w-full bg-green-400 dark:bg-green-500 rounded-t-sm"
                    style={{ height: `${positiveHeight}%`, minHeight: positiveHeight > 0 ? '2px' : 0 }}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* X-axis labels (show first and last date) */}
      <div className="flex justify-between mt-2 text-xs text-light-text-secondary dark:text-dark-text-secondary">
        <span>{trend[0]?.date || ''}</span>
        {trend.length > 1 && <span>{trend[trend.length - 1]?.date || ''}</span>}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-4 mt-2 text-xs text-light-text-secondary dark:text-dark-text-secondary">
        <span className="flex items-center gap-1">
          <div className="w-3 h-3 bg-green-400 dark:bg-green-500 rounded-sm" />
          Positive
        </span>
        <span className="flex items-center gap-1">
          <div className="w-3 h-3 bg-red-400 dark:bg-red-500 rounded-sm" />
          Negative
        </span>
      </div>
    </div>
  );
}

export default FeedbackAnalytics;
