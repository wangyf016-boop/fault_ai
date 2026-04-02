import React, { useState, useRef, useEffect } from 'react';
import { Send, StopCircle, MessageSquare } from 'lucide-react';

const EXAMPLE_QUESTIONS = [
    'How to resolve XX41 alarm?',
    'What are the historical issues related to encoders?',
];

const InputBox = ({ onSend, isLoading }) => {
    const [input, setInput] = useState('');
    const textareaRef = useRef(null);

    const handleSend = () => {
        if (!input.trim()) return;
        onSend(input);
        setInput('');
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
        }
    };

    const handleExampleClick = (question) => {
        setInput(question);
        if (textareaRef.current) {
            textareaRef.current.focus();
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const handleInput = (e) => {
        const target = e.target;
        target.style.height = 'auto';
        target.style.height = `${Math.min(target.scrollHeight, 150)}px`;
        setInput(target.value);
    };

    return (
        <div className="w-full max-w-4xl mx-auto p-4 z-10 relative">
            {/* 示例问题 */}
            {!input && !isLoading && (
                <div className="flex flex-wrap gap-2 mb-4 justify-center animate-in fade-in slide-in-from-bottom-2 duration-300">
                    {EXAMPLE_QUESTIONS.map((question, index) => (
                        <button
                            key={index}
                            onClick={() => handleExampleClick(question)}
                            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-white hover:bg-brand-orange-50 text-slate-500 hover:text-brand-orange-600 border border-slate-200 hover:border-brand-orange-200 rounded-full transition-all shadow-sm hover:shadow-md"
                        >
                            <MessageSquare size={14} className="text-brand-orange-400" />
                            <span className="max-w-[240px] truncate">{question}</span>
                        </button>
                    ))}
                </div>
            )}
            
            <div className="relative flex items-end gap-2 bg-white border border-slate-200 rounded-2xl shadow-lg p-2 focus-within:ring-2 focus-within:ring-brand-orange-100 focus-within:border-brand-orange-400 transition-all">
                <textarea
                    ref={textareaRef}
                    value={input}
                    onChange={handleInput}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask about a fault or diagnosis..."
                    className="flex-1 bg-transparent border-none resize-none outline-none max-h-[150px] py-3 px-2 min-h-[44px] text-slate-700 placeholder:text-slate-400"
                    rows={1}
                />

                {isLoading ? (
                    <button
                        className="p-3 bg-red-500 text-white rounded-xl hover:bg-red-600 transition-colors shadow-md animate-pulse"
                        title="Stop generating"
                    >
                        <StopCircle size={20} />
                    </button>
                ) : (
                    <button
                        onClick={handleSend}
                        disabled={!input.trim()}
                        className={`p-3 rounded-xl transition-all shadow-sm ${input.trim()
                                ? 'bg-gradient-to-r from-brand-orange-500 to-brand-orange-400 text-white hover:shadow-md hover:scale-105 transform'
                                : 'bg-slate-100 text-slate-300 cursor-not-allowed'
                            }`}
                    >
                        <Send size={20} className={input.trim() ? "ml-0.5" : ""} />
                    </button>
                )}
            </div>
            <div className="text-center mt-3">
                <p className="text-xs text-slate-400">
                    AI can make mistakes. Please verify important information.
                </p>
            </div>
        </div>
    );
};

export default InputBox;
