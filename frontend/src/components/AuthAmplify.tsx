import React, { ReactNode, cloneElement, ReactElement } from 'react';
import { BaseProps } from '../@types/common';
import { Authenticator } from '@aws-amplify/ui-react';
import { useTranslation } from 'react-i18next';
import { useAuthenticator } from '@aws-amplify/ui-react';
import { SocialProvider } from '../@types/auth';

type Props = BaseProps & {
  socialProviders: SocialProvider[];
  children: ReactNode;
};

const AuthAmplify: React.FC<Props> = ({ socialProviders, children }) => {
  const { t } = useTranslation();
  const { signOut } = useAuthenticator();
  const enableSignup = import.meta.env.VITE_APP_ENABLE_SIGNUP === 'true';
  const enableForgotPassword = import.meta.env.VITE_APP_ENABLE_FORGOT_PASSWORD === 'true';
  const logoUrl = import.meta.env.VITE_APP_LOGO_URL;

  return (
    <Authenticator
      socialProviders={socialProviders}
      hideSignUp={!enableSignup}
      components={{
        Header: () => (
          <div className="mb-5 mt-10 flex flex-col items-center justify-center gap-3">
            {logoUrl && (
              <img src={logoUrl} alt="Logo" className="h-16 w-16" />
            )}
            <div className="text-3xl text-aws-font-color-light">
              {t('app.name')}
            </div>
          </div>
        ),
        SignIn: {
          Footer() {
            if (!enableForgotPassword) {
              return null;
            }
            return (
              <div className="amplify-flex amplify-authenticator__footer">
                <button
                  type="button"
                  className="amplify-button amplify-field-group__control amplify-button--link"
                  onClick={() => {
                    const event = new CustomEvent('amplify-authenticator-route', {
                      detail: { route: 'forgotPassword' },
                    });
                    window.dispatchEvent(event);
                  }}>
                  Forgot Password?
                </button>
              </div>
            );
          },
        },
      }}>
      <>{cloneElement(children as ReactElement, { signOut })}</>
    </Authenticator>
  );
};

export default AuthAmplify;
