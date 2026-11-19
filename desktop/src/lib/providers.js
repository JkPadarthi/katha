// The AI providers the Muse can talk to (4.1). The server speaks three wire formats —
// Ollama's, OpenAI's chat completions, and Claude's Messages — and nearly every
// provider speaks one of them, so a "provider" here is just a preset: the format, the
// address, and what it needs. Every field stays editable, and "Custom" covers the rest.
//
// `api` is the server's dialect id: 'ollama' | 'openai' | 'messages'.
// `models` are filled in only where the name is known to be right; everywhere else
// the author picks from the provider's own list ("Load models").

export const PROVIDERS = [
  { id: 'claude', label: 'Claude', sub: 'Anthropic', api: 'messages', base: 'https://api.anthropic.com/v1',
    keyed: true, keyAt: 'console.anthropic.com', models: ['claude-sonnet-5-5', 'claude-sonnet-5-5'] },
  { id: 'openai', label: 'OpenAI', sub: 'GPT', api: 'openai', base: 'https://api.openai.com/v1',
    keyed: true, keyAt: 'platform.openai.com' },
  { id: 'openrouter', label: 'OpenRouter', sub: 'many models', api: 'openai', base: 'https://openrouter.ai/api/v1',
    keyed: true, keyAt: 'openrouter.ai/keys' },
  { id: 'commandcode', label: 'Command Code', sub: 'gateway', api: 'openai', base: 'https://api.commandcode.ai/provider/v1',
    keyed: true, keyAt: 'commandcode.ai', wire: true, models: ['deepseek/deepseek-v4-flash', 'deepseek/deepseek-v4-flash'],
    note: 'Claude models on Command Code answer only in the Claude format, the rest in the OpenAI format — picking a model from the list sets it for you.' },
  { id: 'opencode-go', label: 'OpenCode Go', sub: 'subscription', api: 'openai', base: 'https://opencode.ai/zen/go/v1',
    keyed: true, keyAt: 'opencode.ai/auth', wire: true,
    note: 'Your OpenCode Go subscription key. Most Go models use the OpenAI format; if a model asks for /messages, switch the format below.' },
  { id: 'opencode', label: 'OpenCode Zen', sub: 'pay as you go', api: 'openai', base: 'https://opencode.ai/zen/v1',
    keyed: true, keyAt: 'opencode.ai/auth', wire: true,
    note: 'Claude models on OpenCode Zen use the Claude (Messages) format — switch the format below for them.' },
  { id: 'gemini', label: 'Gemini', sub: 'Google', api: 'openai', base: 'https://generativelanguage.googleapis.com/v1beta/openai',
    keyed: true, keyAt: 'aistudio.google.com' },
  { id: 'deepseek', label: 'DeepSeek', sub: '', api: 'openai', base: 'https://api.deepseek.com/v1',
    keyed: true, keyAt: 'platform.deepseek.com' },
  { id: 'mistral', label: 'Mistral', sub: '', api: 'openai', base: 'https://api.mistral.ai/v1',
    keyed: true, keyAt: 'console.mistral.ai' },
  { id: 'groq', label: 'Groq', sub: 'fast', api: 'openai', base: 'https://api.groq.com/openai/v1',
    keyed: true, keyAt: 'console.groq.com' },
  { id: 'xai', label: 'xAI', sub: 'Grok', api: 'openai', base: 'https://api.x.ai/v1',
    keyed: true, keyAt: 'console.x.ai' },
  { id: 'ollama', label: 'Ollama', sub: 'your network', api: 'ollama', base: '', placeholder: 'http://100.x.y.z:11434',
    keyed: false, note: 'The Ollama box on your network. No key needed.' },
  { id: 'lmstudio', label: 'LM Studio', sub: 'local', api: 'openai', base: 'http://localhost:1234/v1',
    keyed: false, optionalKey: true,
    note: 'Any OpenAI-compatible server you run yourself (LM Studio, llama.cpp, vLLM). "localhost" means the machine Katha runs on.' },
  { id: 'custom', label: 'Custom', sub: 'any gateway', api: 'openai', base: '', placeholder: 'https://gateway.example/v1',
    keyed: true, wire: true }
]

export const WIRES = [
  { id: 'openai', label: 'OpenAI format', hint: 'POST …/chat/completions — most providers' },
  { id: 'messages', label: 'Claude format', hint: 'POST …/messages — Anthropic and Claude on gateways' },
  { id: 'ollama', label: 'Ollama format', hint: 'POST …/api/chat' }
]

const norm = (u) => (u || '').trim().toLowerCase().replace(/\/+$/, '')

export const providerById = (id) => PROVIDERS.find((p) => p.id === id) || PROVIDERS[PROVIDERS.length - 1]

// Which preset a saved connection is: the one at its address, else Ollama for the
// Ollama format, else Custom.
export function detectProvider(api, base) {
  const b = norm(base)
  const hit = PROVIDERS.find((p) => p.base && norm(p.base) === b && (p.api === api || p.wire))
  if (hit) return hit.id
  return api === 'ollama' ? 'ollama' : 'custom'
}
