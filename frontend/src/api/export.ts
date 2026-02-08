/**
 * Export API Client
 *
 * Handles exporting analysis results to CSV files
 */

const API_BASE_URL = '/api'

interface ExportRequest {
  data: Array<Record<string, any>>
  filename?: string
  columns?: string[]
}

/**
 * Export data as CSV file
 * @param data Array of data objects to export
 * @param filename Optional filename (default: "export.csv")
 * @param columns Optional column order
 */
export async function exportResultsAsCSV(
  data: Array<Record<string, any>>,
  filename?: string,
  columns?: string[]
): Promise<void> {
  const requestBody: ExportRequest = {
    data,
    filename: filename || 'export.csv',
    columns
  }

  const response = await fetch(`${API_BASE_URL}/export/results`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(requestBody),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to export data' }))
    throw new Error(error.detail || 'Failed to export data')
  }

  // Get the blob from response
  const blob = await response.blob()

  // Create a download link and trigger download
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename || 'export.csv'
  document.body.appendChild(link)
  link.click()

  // Cleanup
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}
