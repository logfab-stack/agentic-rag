/**
 * Ngrok API client for checking tunnel status
 *
 * Used to display the ngrok webhook URL in the WhatsApp Settings page.
 */

export interface NgrokTunnel {
  name: string
  public_url: string
  proto: string
  config_addr: string
}

export interface NgrokStatusResponse {
  running: boolean
  public_url: string | null
  webhook_url: string | null
  tunnels: NgrokTunnel[]
  error: string | null
}

/**
 * Fetch ngrok tunnel status from the backend
 *
 * The backend queries ngrok's local API (http://127.0.0.1:4040/api/tunnels)
 * and returns the status including the public URL and webhook URL.
 */
export async function fetchNgrokStatus(): Promise<NgrokStatusResponse> {
  const response = await fetch('/api/ngrok/status')
  if (!response.ok) {
    throw new Error(`Failed to fetch ngrok status: ${response.statusText}`)
  }
  return response.json()
}
