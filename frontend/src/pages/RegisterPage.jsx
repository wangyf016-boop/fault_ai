import React from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Check, X } from 'lucide-react';

const RegisterPage = () => {
    const navigate = useNavigate();

    const handleRegister = (e) => {
        e.preventDefault();
        navigate('/login');
    };

    return (
        <div className="h-screen w-full flex items-center justify-center bg-muted">
            <div className="w-full max-w-md bg-background p-8 rounded-lg shadow-lg border border-border">
                <h1 className="text-2xl font-bold text-center mb-6 text-primary">Create Account</h1>
                <form onSubmit={handleRegister} className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium mb-1">First Name</label>
                            <input type="text" className="input" placeholder="John" />
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1">Last Name</label>
                            <input type="text" className="input" placeholder="Doe" />
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">Email</label>
                        <input type="email" className="input" placeholder="john@example.com" />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">Password</label>
                        <input type="password" className="input" placeholder="••••••••" />
                        <div className="mt-2 flex gap-1">
                            <div className="h-1 flex-1 bg-success rounded-full"></div>
                            <div className="h-1 flex-1 bg-success rounded-full"></div>
                            <div className="h-1 flex-1 bg-muted rounded-full"></div>
                        </div>
                        <p className="text-xs text-success mt-1">Strong password</p>
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">Confirm Password</label>
                        <input type="password" className="input" placeholder="••••••••" />
                    </div>

                    <div className="flex items-center gap-2">
                        <input type="checkbox" id="terms" className="rounded border-gray-300 text-primary focus:ring-primary" />
                        <label htmlFor="terms" className="text-sm text-muted-foreground">
                            I agree to the <a href="#" className="text-primary hover:underline">Terms of Service</a>
                        </label>
                    </div>

                    <button type="submit" className="btn btn-primary w-full mt-4">
                        Create Account
                    </button>
                </form>

                <div className="mt-6 text-center text-sm text-muted-foreground">
                    Already have an account?{' '}
                    <Link to="/login" className="text-primary hover:underline font-medium">
                        Sign in
                    </Link>
                </div>
            </div>
        </div>
    );
};

export default RegisterPage;
