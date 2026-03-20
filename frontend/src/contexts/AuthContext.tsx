import React, { createContext, useContext, useState, useEffect } from "react";
import { User } from "../types";
import api from "../utils/api";

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    full_name: string,
    password: string,
  ) => Promise<void>;
  logout: () => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      fetchUser();
    } else {
      setLoading(false);
    }
  }, []);

  const fetchUser = async () => {
    try {
      const response = await api.get("/auth/me");
      setUser(response.data);
    } catch (error) {
      localStorage.removeItem("token");
      localStorage.removeItem("refreshToken");
    } finally {
      setLoading(false);
    }
  };

  const login = async (email: string, password: string) => {
    const response = await api.post("/auth/login", { email, password });
    const { access_token, refresh_token } = response.data;

    localStorage.setItem("token", access_token);
    localStorage.setItem("refreshToken", refresh_token);
    await fetchUser();
  };

  const register = async (
    email: string,
    full_name: string,
    password: string,
  ) => {
    const response = await api.post("/auth/register", {
      email,
      full_name,
      password,
    });
    const { access_token, refresh_token } = response.data;

    localStorage.setItem("token", access_token);
    localStorage.setItem("refreshToken", refresh_token);
    await fetchUser();
  };

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("refreshToken");
    setUser(null);
  };

  const value = {
    user,
    login,
    register,
    logout,
    loading,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
