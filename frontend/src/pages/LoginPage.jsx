import React from 'react';
import { useNavigate } from 'react-router-dom';

const LoginPage = () => {
    const navigate = useNavigate();

    const handleLogin = (e) => {
        e.preventDefault();
        // Mock login
        navigate('/chat');
    };

    return (
        <div className="h-screen w-full flex items-center justify-center bg-muted">
            <div className="w-full max-w-md bg-background p-8 rounded-lg shadow-lg border border-border">
                <h1 className="text-2xl font-bold text-center mb-6 text-primary">Maintenance  Intelligent Expert</h1>
                <form onSubmit={handleLogin} className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1">Email</label>
                        <input type="email" className="input" placeholder="admin@example.com" />
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">Password</label>
                        <input type="password" className="input" placeholder="••••••••" />
                    </div>
                    <button type="submit" className="btn btn-primary w-full mt-4">
                        Sign In
                    </button>
                </form>
            </div>
        </div>
    );
};

export default LoginPage;
