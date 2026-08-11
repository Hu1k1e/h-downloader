import sys

file_path = r"c:\Users\svija\.gemini\antigravity\scratch\Enthusan Downloader\frontend\src\pages\Settings.jsx"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Chunk 1
state_target = """    const [qbtMsg, setQbtMsg] = useState('')
    const [qbtCategories, setQbtCategories] = useState([])"""
state_replacement = """    const [qbtMsg, setQbtMsg] = useState('')
    const [qbtCategories, setQbtCategories] = useState([])

    const [llmTesting, setLlmTesting] = useState(false)
    const [llmStatus, setLlmStatus] = useState(null)
    const [llmMsg, setLlmMsg] = useState('')"""
if state_target in content:
    content = content.replace(state_target, state_replacement)
else:
    print("Could not find state target")

# Chunk 2
load_target = """                auto_delete_failed_torrents_hours: data.auto_delete_failed_torrents_hours ?? 24,
                min_file_size_mb: data.min_file_size_mb ?? 800,
                max_file_size_mb: data.max_file_size_mb ?? 15000,
                enable_jellyseerr_auto_request: data.enable_jellyseerr_auto_request ?? true,
            })"""
load_replacement = """                auto_delete_failed_torrents_hours: data.auto_delete_failed_torrents_hours ?? 24,
                min_file_size_mb: data.min_file_size_mb ?? 800,
                max_file_size_mb: data.max_file_size_mb ?? 15000,
                enable_jellyseerr_auto_request: data.enable_jellyseerr_auto_request ?? true,
                llm_enabled: data.llm_enabled ?? false,
                llm_api_url: data.llm_api_url || 'https://api.freellmapi.com/v1',
                llm_api_key: '',
                llm_model: data.llm_model || 'gpt-3.5-turbo',
            })"""
if load_target in content:
    content = content.replace(load_target, load_replacement)
else:
    print("Could not find load target")

# Chunk 3
test_target = """            setQbtTesting(false)
        }
    }


    
    async function testSonarr() {"""
test_replacement = """            setQbtTesting(false)
        }
    }

    async function testLlm() {
        setLlmTesting(true)
        setLlmStatus(null)
        setLlmMsg('')
        try {
            const res = await api.testLlm({
                url: formData.llm_api_url,
                key: formData.llm_api_key || '',
                model: formData.llm_model
            })
            setLlmStatus('ok')
            setLlmMsg(res.message)
        } catch (e) {
            setLlmStatus('err')
            setLlmMsg(e.message)
        } finally {
            setLlmTesting(false)
        }
    }

    
    async function testSonarr() {"""
if test_target in content:
    content = content.replace(test_target, test_replacement)
else:
    print("Could not find test target")


# Chunk 4
render_target = """            </div>

            {/* Scheduler */}"""
render_replacement = """            </div>

            {/* LLM Integration */}
            <div className="card settings-section" style={{ marginBottom: 16 }}>
                <div className="settings-section-title">LLM Integration (FreeLLMAPI)</div>
                <div className="form-row">
                    <span className="form-label">Enable LLM <Tooltip text="Use LLM to intelligently parse tracker search results before falling back to regex logic" /></span>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', color: 'var(--text-primary)' }}>
                        <input type="checkbox" name="llm_enabled" checked={formData.llm_enabled} onChange={e => setFormData(p => ({...p, llm_enabled: e.target.checked}))} />
                        Enable intelligent search parsing
                    </label>
                </div>
                {formData.llm_enabled && (
                    <>
                        <div className="form-row">
                            <span className="form-label">API URL <Tooltip text="The base URL of the OpenAI-compatible API" /></span>
                            <input className="form-input" name="llm_api_url" value={formData.llm_api_url} onChange={handleChange} placeholder="https://api.freellmapi.com/v1" />
                        </div>
                        <div className="form-row">
                            <span className="form-label">API Key <Tooltip text="Your API Key" /></span>
                            <input className="form-input" type="password" name="llm_api_key" value={formData.llm_api_key} onChange={handleChange} placeholder={settings.llm_api_key_set ? '•••••••• (Set - Type to change)' : 'Not set'} />
                        </div>
                        <div className="form-row">
                            <span className="form-label">Model <Tooltip text="The specific model ID to use" /></span>
                            <input className="form-input" name="llm_model" value={formData.llm_model} onChange={handleChange} placeholder="gpt-3.5-turbo" />
                        </div>
                        <div className="form-row">
                            <span className="form-label">Connection</span>
                            <div className="connection-test-row">
                                <button className="btn btn-secondary btn-sm" onClick={testLlm} disabled={llmTesting}>
                                    {llmTesting ? <><span className="spinner" /> Testing...</> : 'Test Connection'}
                                </button>
                                {llmStatus === 'ok' && <span className="test-result ok">✓ {llmMsg}</span>}
                                {llmStatus === 'err' && <span className="test-result err">✗ {llmMsg}</span>}
                            </div>
                        </div>
                    </>
                )}
            </div>

            {/* Scheduler */}"""
if render_target in content:
    content = content.replace(render_target, render_replacement)
else:
    print("Could not find render target")

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
