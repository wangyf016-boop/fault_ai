import React, { useState, useEffect } from 'react';
import { Save, RefreshCw, CheckCircle, AlertCircle, Eye, EyeOff, RotateCcw, Settings, MessageSquare } from 'lucide-react';
import { getLLMConfig, saveLLMConfig, testLLMConnection, getPromptsConfig, savePromptsConfig, resetPromptsConfig } from '../services/settingsApi';

const SettingsPage = () => {
    // LLM 配置状态
    const [config, setConfig] = useState({
        llm_type: 'ollama',
        api_base_url: '',
        api_key: '',
        model_name: '',
        ollama_base_url: 'http://127.0.0.1:1235',
        ollama_model: 'Qwen3-30B-A3B-Instruct-2507-IQ4_NL.gguf',
    });
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [message, setMessage] = useState(null);
    const [showApiKey, setShowApiKey] = useState(false);

    // 提示词配置状态
    const [prompts, setPrompts] = useState({
        system_prompt_new: '',
        system_prompt_followup: '',
        system_prompt_history: '',
        neo4j_rag_prompt: '',
    });
    const [promptsLoading, setPromptsLoading] = useState(true);
    const [promptsSaving, setPromptsSaving] = useState(false);
    const [promptsResetting, setPromptsResetting] = useState(false);
    const [promptsMessage, setPromptsMessage] = useState(null);

    // 当前激活的标签页
    const [activeTab, setActiveTab] = useState('llm');

    useEffect(() => {
        loadConfig();
        loadPrompts();
    }, []);

    const loadConfig = async () => {
        try {
            setLoading(true);
            const data = await getLLMConfig();
            setConfig(data);
        } catch (err) {
            setMessage({ type: 'error', text: 'Failed to load configuration: ' + err.message });
        } finally {
            setLoading(false);
        }
    };

    const loadPrompts = async () => {
        try {
            setPromptsLoading(true);
            const data = await getPromptsConfig();
            setPrompts(data);
        } catch (err) {
            setPromptsMessage({ type: 'error', text: 'Failed to load prompts: ' + err.message });
        } finally {
            setPromptsLoading(false);
        }
    };

    const handleSave = async () => {
        try {
            setSaving(true);
            await saveLLMConfig(config);
            // 同步保存到 localStorage，前端聊天时优先使用
            localStorage.setItem('llm_config', JSON.stringify({
                llm_type: config.llm_type,
                ollama_base_url: config.ollama_base_url,
                ollama_model: config.ollama_model,
            }));
            setMessage({ type: 'success', text: 'Configuration saved and applied immediately (no backend restart required)' });
        } catch (err) {
            setMessage({ type: 'error', text: 'Save failed: ' + err.message });
        } finally {
            setSaving(false);
        }
    };

    const handleTest = async () => {
        try {
            setTesting(true);
            setMessage(null);
            // 统一走后端 API 测试，避免 CORS 问题
            const result = await testLLMConnection(config);
            if (result.success) {
                setMessage({ type: 'success', text: result.response || 'Connection successful' });
            } else {
                setMessage({ type: 'error', text: `Connection failed: ${result.error}` });
            }
        } catch (err) {
            setMessage({ type: 'error', text: 'Test failed: ' + err.message });
        } finally {
            setTesting(false);
        }
    };

    const handleChange = (field, value) => {
        setConfig(prev => ({ ...prev, [field]: value }));
        setMessage(null);
    };

    const handlePromptChange = (field, value) => {
        setPrompts(prev => ({ ...prev, [field]: value }));
        setPromptsMessage(null);
    };

    const handlePromptsSave = async () => {
        try {
            setPromptsSaving(true);
            await savePromptsConfig(prompts);
            setPromptsMessage({ type: 'success', text: 'Prompt configuration saved' });
        } catch (err) {
            setPromptsMessage({ type: 'error', text: 'Save failed: ' + err.message });
        } finally {
            setPromptsSaving(false);
        }
    };

    const handlePromptsReset = async () => {
        if (!window.confirm('Are you sure you want to reset to default prompts?')) return;
        try {
            setPromptsResetting(true);
            await resetPromptsConfig();
            const nextPrompts = await getPromptsConfig();
            setPrompts(nextPrompts);
            setPromptsMessage({ type: 'success', text: 'Reset to default prompts' });
        } catch (err) {
            setPromptsMessage({ type: 'error', text: 'Reset failed: ' + err.message });
        } finally {
            setPromptsResetting(false);
        }
    };

    if (loading || promptsLoading) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="flex flex-col items-center gap-4">
                    <RefreshCw className="animate-spin text-brand-orange-500" size={32} />
                    <p className="text-slate-500 font-medium">Loading settings...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto space-y-6 pb-12">
            <div className="flex flex-col gap-2">
                 <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-brand-orange-500 to-brand-purple-600">
                    System Settings
                </h1>
                <p className="text-slate-500">Configure your LLM provider and system prompts.</p>
            </div>

            {/* 标签页切换 */}
            <div className="flex bg-white/50 backdrop-blur-sm p-1.5 rounded-2xl border border-slate-200 shadow-sm w-fit">
                <button
                    onClick={() => setActiveTab('llm')}
                    className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
                        activeTab === 'llm'
                            ? 'bg-white text-brand-orange-600 shadow-md ring-1 ring-slate-100'
                            : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
                    }`}
                >
                    <Settings size={16} />
                    LLM Configuration
                </button>
                <button
                    onClick={() => setActiveTab('prompts')}
                    className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
                        activeTab === 'prompts'
                            ? 'bg-white text-brand-orange-600 shadow-md ring-1 ring-slate-100'
                            : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
                    }`}
                >
                    <MessageSquare size={16} />
                    Prompt Tuning
                </button>
            </div>

            {/* LLM 配置面板 */}
            {activeTab === 'llm' && (
                <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <h3 className="text-xl font-bold text-slate-800 mb-6 flex items-center gap-2">
                        <span className="w-1.5 h-6 bg-brand-orange-500 rounded-full"/>
                        Provider Settings
                    </h3>
                
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                        {/* 左侧表单 */}
                        <div className="space-y-6">
                            <div className="space-y-2">
                                <label className="block text-sm font-bold text-slate-700">LLM Type</label>
                                <div className="relative">
                                    <select
                                        value={config.llm_type}
                                        onChange={(e) => handleChange('llm_type', e.target.value)}
                                        className="w-full pl-4 pr-10 py-3 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 transition-all appearance-none font-medium text-slate-700"
                                    >
                                        <option value="glm">Zhipu GLM (Cloud)</option>
                                        <option value="ollama">Ollama (Local)</option>
                                        <option value="openai">OpenAI Compatible</option>
                                    </select>
                                    <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
                                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                                    </div>
                                </div>
                            </div>

                            {/* GLM / OpenAI 配置 */}
                            {(config.llm_type === 'glm' || config.llm_type === 'openai') && (
                                <>
                                    <div className="space-y-2">
                                        <label className="block text-sm font-bold text-slate-700">API Base URL</label>
                                        <input
                                            type="text"
                                            value={config.api_base_url}
                                            onChange={(e) => handleChange('api_base_url', e.target.value)}
                                            placeholder="e.g. https://open.bigmodel.cn/api/paas/v4/"
                                            className="w-full px-4 py-3 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 transition-all placeholder:text-slate-400"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="block text-sm font-bold text-slate-700">API Key</label>
                                        <div className="relative">
                                            <input
                                                type={showApiKey ? 'text' : 'password'}
                                                value={config.api_key}
                                                onChange={(e) => handleChange('api_key', e.target.value)}
                                                placeholder="sk-..."
                                                className="w-full px-4 py-3 pr-12 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 transition-all placeholder:text-slate-400 font-mono"
                                            />
                                            <button
                                                type="button"
                                                onClick={() => setShowApiKey(!showApiKey)}
                                                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-brand-orange-500 p-1 rounded-md hover:bg-brand-orange-50 transition-colors"
                                            >
                                                {showApiKey ? <EyeOff size={18} /> : <Eye size={18} />}
                                            </button>
                                        </div>
                                    </div>
                                    <div className="space-y-2">
                                        <label className="block text-sm font-bold text-slate-700">Model Name</label>
                                        <input
                                            type="text"
                                            value={config.model_name}
                                            onChange={(e) => handleChange('model_name', e.target.value)}
                                            placeholder="e.g. glm-4-flash"
                                            className="w-full px-4 py-3 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 transition-all placeholder:text-slate-400 font-mono"
                                        />
                                    </div>
                                </>
                            )}

                            {/* Ollama 配置 */}
                            {config.llm_type === 'ollama' && (
                                <>
                                    <div className="space-y-2">
                                        <label className="block text-sm font-bold text-slate-700">Ollama Base URL</label>
                                        <input
                                            type="text"
                                            value={config.ollama_base_url}
                                            onChange={(e) => handleChange('ollama_base_url', e.target.value)}
                                            placeholder="http://host.docker.internal:1235"
                                            className="w-full px-4 py-3 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 transition-all placeholder:text-slate-400 font-mono"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="block text-sm font-bold text-slate-700">Model Name</label>
                                        <input
                                            type="text"
                                            value={config.ollama_model}
                                            onChange={(e) => handleChange('ollama_model', e.target.value)}
                                            placeholder="e.g. Qwen3-30B-2507-instruct"
                                            className="w-full px-4 py-3 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 transition-all placeholder:text-slate-400 font-mono"
                                        />
                                    </div>
                                </>
                            )}
                        </div>

                        {/* 右侧说明 */}
                        <div className="space-y-6">
                            <div className="bg-blue-50/50 border border-blue-100 rounded-xl p-6 text-sm text-blue-800 leading-relaxed">
                                <h4 className="font-bold mb-3 flex items-center gap-2">
                                    <AlertCircle size={18} />
                                    Configuration Guide
                                </h4>
                                <ul className="space-y-2 list-disc list-inside opacity-90">
                                    <li><b>Zhipu GLM</b>: Cloud-based models from Zhipu AI. Reliable and powerful.</li>
                                    <li><b>Ollama</b>: Run models locally. Requires Ollama installed and running.</li>
                                    <li><b>OpenAI Compatible</b>: Connect to any OpenAI-compatible API (e.g., DeepSeek, Moonshot).</li>
                                    <li>Most configuration changes take effect immediately for new requests.</li>
                                </ul>
                            </div>
                        </div>
                    </div>

                    {/* 消息提示 */}
                    {message && (
                        <div className={`flex items-center gap-3 p-4 rounded-xl mt-6 animate-in slide-in-from-top-2 ${
                            message.type === 'success' 
                                ? 'bg-green-50 border border-green-200 text-green-700' 
                                : 'bg-red-50 border border-red-200 text-red-700'
                        }`}>
                            {message.type === 'success' ? <CheckCircle size={20} className="shrink-0" /> : <AlertCircle size={20} className="shrink-0" />}
                            <span className="font-medium">{message.text}</span>
                        </div>
                    )}

                    {/* 操作按钮 */}
                    <div className="flex gap-4 mt-8 pt-6 border-t border-slate-100">
                        <button
                            onClick={handleTest}
                            disabled={testing}
                            className="flex items-center gap-2 px-6 py-2.5 border border-slate-200 rounded-xl text-slate-600 font-semibold hover:bg-slate-50 hover:text-slate-900 transition-all disabled:opacity-50"
                        >
                            {testing ? <RefreshCw className="animate-spin" size={18} /> : <RefreshCw size={18} />}
                            <span>Test Connection</span>
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className="flex items-center gap-2 px-8 py-2.5 bg-gradient-to-r from-brand-orange-500 to-brand-orange-600 text-white rounded-xl font-semibold shadow-md shadow-brand-orange-200 hover:shadow-lg hover:from-brand-orange-600 hover:to-brand-orange-700 transition-all transform hover:-translate-y-0.5 disabled:opacity-50 disabled:translate-y-0"
                        >
                            {saving ? <RefreshCw className="animate-spin" size={18} /> : <Save size={18} />}
                            <span>Save Configuration</span>
                        </button>
                    </div>
                </div>
            )}

            {/* 提示词配置面板 */}
            {activeTab === 'prompts' && (
                <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <h3 className="text-xl font-bold text-slate-800 mb-6 flex items-center gap-2">
                        <span className="w-1.5 h-6 bg-brand-purple-500 rounded-full"/>
                        System Prompts
                    </h3>
                    
                    <div className="space-y-8">
                        <div>
                            <div className="flex justify-between items-baseline mb-2">
                                <label className="block text-sm font-bold text-slate-700">New Query System Prompt</label>
                                <span className="text-xs text-slate-400 font-mono">system_prompt_new</span>
                            </div>
                            <textarea
                                value={prompts.system_prompt_new}
                                onChange={(e) => handlePromptChange('system_prompt_new', e.target.value)}
                                rows={6}
                                className="w-full px-4 py-3 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-purple-100 focus:border-brand-purple-400 transition-all font-mono text-sm leading-relaxed"
                            />
                        </div>

                        <div>
                            <div className="flex justify-between items-baseline mb-2">
                                <label className="block text-sm font-bold text-slate-700">Follow-up System Prompt</label>
                                <span className="text-xs text-slate-400 font-mono">system_prompt_followup</span>
                            </div>
                            <textarea
                                value={prompts.system_prompt_followup}
                                onChange={(e) => handlePromptChange('system_prompt_followup', e.target.value)}
                                rows={6}
                                className="w-full px-4 py-3 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-purple-100 focus:border-brand-purple-400 transition-all font-mono text-sm leading-relaxed"
                            />
                        </div>

                        <div>
                            <div className="flex justify-between items-baseline mb-2">
                                <label className="block text-sm font-bold text-slate-700">History System Prompt</label>
                                <span className="text-xs text-slate-400 font-mono">system_prompt_history</span>
                            </div>
                            <textarea
                                value={prompts.system_prompt_history}
                                onChange={(e) => handlePromptChange('system_prompt_history', e.target.value)}
                                rows={6}
                                className="w-full px-4 py-3 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-purple-100 focus:border-brand-purple-400 transition-all font-mono text-sm leading-relaxed"
                            />
                        </div>

                        <div>
                            <div className="flex justify-between items-baseline mb-2">
                                <label className="block text-sm font-bold text-slate-700">RAG Generation Prompt</label>
                                <span className="text-xs text-slate-400 font-mono">neo4j_rag_prompt</span>
                            </div>
                            <textarea
                                value={prompts.neo4j_rag_prompt}
                                onChange={(e) => handlePromptChange('neo4j_rag_prompt', e.target.value)}
                                rows={8}
                                className="w-full px-4 py-3 border border-slate-200 rounded-xl bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-purple-100 focus:border-brand-purple-400 transition-all font-mono text-sm leading-relaxed"
                            />
                        </div>

                        {promptsMessage && (
                            <div className={`flex items-center gap-3 p-4 rounded-xl mt-6 ${
                                promptsMessage.type === 'success' 
                                    ? 'bg-green-50 border border-green-200 text-green-700' 
                                    : 'bg-red-50 border border-red-200 text-red-700'
                            }`}>
                                {promptsMessage.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
                                <span className="font-medium">{promptsMessage.text}</span>
                            </div>
                        )}

                        <div className="flex justify-between items-center pt-6 border-t border-slate-100">
                             <div className="text-xs text-slate-400">
                                <span className="font-semibold">Variables:</span> {'{context}'}, {'{question}'}, {'{chat_history}'}
                            </div>
                            <div className="flex gap-3">
                                <button
                                    onClick={handlePromptsReset}
                                    disabled={promptsResetting}
                                    className="flex items-center gap-2 px-4 py-2.5 text-red-500 hover:text-red-700 hover:bg-red-50 rounded-xl transition-colors font-medium text-sm disabled:opacity-50"
                                >
                                    {promptsResetting ? <RefreshCw className="animate-spin" size={16} /> : <RotateCcw size={16} />}
                                    <span>Reset to Default</span>
                                </button>
                                <button
                                    onClick={handlePromptsSave}
                                    disabled={promptsSaving}
                                    className="flex items-center gap-2 px-8 py-2.5 bg-brand-purple-600 text-white rounded-xl font-semibold shadow-md shadow-brand-purple-200 hover:shadow-lg hover:bg-brand-purple-700 transition-all transform hover:-translate-y-0.5 disabled:opacity-50 disabled:translate-y-0"
                                >
                                    {promptsSaving ? <RefreshCw className="animate-spin" size={18} /> : <Save size={18} />}
                                    <span>Save Prompts</span>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default SettingsPage;
