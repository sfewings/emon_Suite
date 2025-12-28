import numpy as np
from scipy import linalg
from matplotlib import pyplot as plt

 #started with https://github.com/nliaudat/magnetometer_calibration/blob/main/calibrate.py
 #this corrected code by S. James Remington, see issue #1 in above contribution.
 #required data input file: x,y,z values in .csv (text, comma separated value) format.
 # see example mag3_raw.csv, .out
 
class Magnetometer(object):
    
    '''
     references :
        -  https://teslabs.com/articles/magnetometer-calibration/      
        -  https://www.best-microcontroller-projects.com/hmc5883l.html

    '''
    MField = 1000  #arbitrary norm of magnetic field vectors

    def __init__(self, F=MField): 


        # initialize values
        self.F   = F
        self.b   = np.zeros([3, 1])
        self.A_1 = np.eye(3)
        
    def run(self):

        data = np.loadtxt(".\\Tests\\ICM_20948-AHRS\\acc_mag_raw.csv",delimiter=',')
        #data = np.loadtxt(".\\Tests\\ICM_20948-AHRS\\mag_raw.csv", delimiter=',', encoding='utf-8-sig')

        # ensure 2D shape when a single line is present
        if data.ndim == 1 and data.size == 6:
            data = data.reshape(1, 6)

        if data.shape[1] < 6:
            raise ValueError("Expected at least 6 columns: mag_x,mag_y,mag_z, acc_x,acc_y,acc_z")

        # split into magnetometer (first 3 cols) and accelerometer (last 3 cols)
        a_data = data[:, 0:3].astype(float)
        m_data = data[:, 3:6].astype(float)

        print("First 5 rows raw:\n", data[:5])
        print("shape of m_data array:",m_data.shape)
        print("shape of a_data array:",a_data.shape)
        #print("datatype of data:",data.dtype)

        m_plot_result = self.calibrate_data( a_data, "magnetometer", "A_B", "A_Ainv")        
        a_plot_result = self.calibrate_data( m_data, "accelerometer", "M_B", "M_Ainv")     
        
        plt.rcParams["figure.autolayout"] = True
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
        ax.scatter(m_plot_result[:,0], m_plot_result[:,1], m_plot_result[:,2], marker='o', color='g', label='magnetometer')
        ax.scatter(a_plot_result[:,0], a_plot_result[:,1], a_plot_result[:,2], marker='o', color='b', label='accelerometer')
        ax.set_xlabel('X')
        ax.set_ylabel('Y')
        ax.set_zlabel('Z')
        ax.legend(loc='upper right')
        plt.show()
   


    def calibrate_data(self, data, sensor_name, name_B, name_Ainv):
            # ellipsoid fit
        s = np.array(data).T
        M, n, d = self.__ellipsoid_fit(s)

        # calibration parameters
        M_1 = linalg.inv(M)
        self.b = -np.dot(M_1, n)
        self.A_1 = np.real(self.F / np.sqrt(np.dot(n.T, np.dot(M_1, n)) - d) * linalg.sqrtm(M))

        print("/*************************/" )        
        print(f"//code to paste : for {sensor_name}")
        print("/*************************/" )
        self.b = np.round(self.b,2)
        print(f"float {name_B} [3] = {{{self.b[0]}, {self.b[1]}, {self.b[2]}}};")
        print("\n")
        
        self.A_1 = np.round(self.A_1,5)
        print(f"float {name_Ainv}[3][3] = {{")
        print(f"{{ {self.A_1[0,0]}, {self.A_1[0,1]}, {self.A_1[0,2]} }},")
        print(f"{{ {self.A_1[1,0]}, {self.A_1[1,1]}, {self.A_1[1,2]} }},")
        print(f"{{ {self.A_1[2,0]}, {self.A_1[2,1]}, {self.A_1[2,2]} }}}};")
        print("\n")

        
        #print("M:\n", M, "\nn:\n", n, "\nd:\n", d)        
        #print("M_1:\n",M_1, "\nb:\n", self.b, "\nA_1:\n", self.A_1)
        
        #print("\nData normalized to ",self.F)        
        #print("Soft iron transformation matrix:\n",self.A_1)
        #print("Hard iron bias:\n", self.b)

        #plt.rcParams["figure.autolayout"] = True

        result = [] 
        for row in data: 
        
            # subtract the hard iron offset
            xm_off  = row[0]-self.b[0]
            ym_off  = row[1]-self.b[1]
            zm_off  = row[2]-self.b[2]
            
            #multiply by the inverse soft iron offset
            xm_cal = xm_off *  self.A_1[0,0] + ym_off *  self.A_1[0,1]  + zm_off *  self.A_1[0,2] 
            ym_cal = xm_off *  self.A_1[1,0] + ym_off *  self.A_1[1,1]  + zm_off *  self.A_1[1,2] 
            zm_cal = xm_off *  self.A_1[2,0] + ym_off *  self.A_1[2,1]  + zm_off *  self.A_1[2,2] 

            result = np.append(result, np.array([xm_cal, ym_cal, zm_cal]) )#, axis=0 )

        result_plot_points = result.reshape(-1, 3)
        # fig = plt.figure()
        # ax = fig.add_subplot(111, projection='3d')
        # ax.scatter(result[:,0], result[:,1], result[:,2], marker='o', color='g')
        # plt.show()
        
        # print("First 5 rows calibrated:\n", result[:5])
		
        #save corrected data to file "out.txt"
        #np.savetxt('out.txt', result, fmt='%f', delimiter=' ,')

        return result_plot_points



    def __ellipsoid_fit(self, s):
        ''' Estimate ellipsoid parameters from a set of points.

            Parameters
            ----------
            s : array_like
              The samples (M,N) where M=3 (x,y,z) and N=number of samples.

            Returns
            -------
            M, n, d : array_like, array_like, float
              The ellipsoid parameters M, n, d.

            References
            ----------
            .. [1] Qingde Li; Griffiths, J.G., "Least squares ellipsoid specific
               fitting," in Geometric Modeling and Processing, 2004.
               Proceedings, vol., no., pp.335-340, 2004
        '''

        # D (samples)
        D = np.array([s[0]**2., s[1]**2., s[2]**2.,
                      2.*s[1]*s[2], 2.*s[0]*s[2], 2.*s[0]*s[1],
                      2.*s[0], 2.*s[1], 2.*s[2], np.ones_like(s[0])])

        # S, S_11, S_12, S_21, S_22 (eq. 11)
        S = np.dot(D, D.T)
        S_11 = S[:6,:6]
        S_12 = S[:6,6:]
        S_21 = S[6:,:6]
        S_22 = S[6:,6:]

        # C (Eq. 8, k=4)
        C = np.array([[-1,  1,  1,  0,  0,  0],
                      [ 1, -1,  1,  0,  0,  0],
                      [ 1,  1, -1,  0,  0,  0],
                      [ 0,  0,  0, -4,  0,  0],
                      [ 0,  0,  0,  0, -4,  0],
                      [ 0,  0,  0,  0,  0, -4]])

        # v_1 (eq. 15, solution)
        E = np.dot(linalg.inv(C),
                   S_11 - np.dot(S_12, np.dot(linalg.inv(S_22), S_21)))

        E_w, E_v = np.linalg.eig(E)

        v_1 = E_v[:, np.argmax(E_w)]
        if v_1[0] < 0: v_1 = -v_1

        # v_2 (eq. 13, solution)
        v_2 = np.dot(np.dot(-np.linalg.inv(S_22), S_21), v_1)

        # quadratic-form parameters, parameters h and f swapped as per correction by Roger R on Teslabs page
        M = np.array([[v_1[0], v_1[5], v_1[4]],
                      [v_1[5], v_1[1], v_1[3]],
                      [v_1[4], v_1[3], v_1[2]]])
        n = np.array([[v_2[0]],
                      [v_2[1]],
                      [v_2[2]]])
        d = v_2[3]

        return M, n, d
        
        
        
if __name__=='__main__':
        Magnetometer().run()
