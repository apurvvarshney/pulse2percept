# -*implants -*-
"""

Functions for creating retinal implants

"""
import numpy as np
from scipy import interpolate as spi
import copy
import logging

from pulse2percept import utils
from pulse2percept import implants


class MonophasicPulse(utils.TimeSeries):

    def __init__(self, ptype, pdur, tsample, delay_dur=0, stim_dur=None):
        """A pulse with a single phase

        Parameters
        ----------
        ptype : {'anodic', 'cathodic'}
            Pulse type. Anodic pulses have positive current amplitude,
            cathodic pulses have negative amplitude.
        pdur : float
            Pulse duration (s).
        tsample : float
            Sampling time step (s).
        delay_dur : float, optional
            Pulse delay (s). Pulse will be zero-padded (prepended) to deliver
            the pulse only after `delay_dur` milliseconds. Default: 0.
        stim_dur : float, optional
            Stimulus duration (ms). Pulse will be zero-padded (appended) to fit
            the stimulus duration. Default: No additional zero padding,
            `stim_dur` is `pdur`+`delay_dur`.
        """
        if tsample <= 0:
            raise ValueError("tsample must be a non-negative float.")

        if stim_dur is None:
            stim_dur = pdur + delay_dur

        # Convert durations to number of samples
        pulse_size = int(np.round(pdur / tsample))
        delay_size = int(np.round(delay_dur / tsample))
        stim_size = int(np.round(stim_dur / tsample))

        if ptype == 'cathodic':
            pulse = -np.ones(pulse_size)
        elif ptype == 'anodic':
            pulse = np.ones(pulse_size)
        else:
            raise ValueError("Acceptable values for `ptype` are 'anodic', "
                             "'cathodic'.")

        pulse = np.concatenate((np.zeros(delay_size), pulse,
                                np.zeros(stim_size)))
        utils.TimeSeries.__init__(self, tsample, pulse[:stim_size])


class BiphasicPulse(utils.TimeSeries):

    def __init__(self, ptype, pdur, tsample, interphase_dur=0):
        """A charge-balanced pulse with a cathodic and anodic phase

        A single biphasic pulse with duration `pdur` per phase,
        separated by `interphase_dur` is returned.

        Parameters
        ----------
        ptype : {'cathodicfirst', 'anodicfirst'}
            A cathodic-first pulse has the negative phase first, whereas an
            anodic-first pulse has the positive phase first.
        pdur : float
            Duration of single (positive or negative) pulse phase in seconds.
        tsample : float
            Sampling time step in seconds.
        interphase_dur : float, optional
            Duration of inter-phase interval (between positive and negative
            pulse) in seconds. Default: 0.
        """
        if tsample <= 0:
            raise ValueError("tsample must be a non-negative float.")

        # Get the two monophasic pulses
        on = MonophasicPulse('anodic', pdur, tsample, 0, pdur)
        off = MonophasicPulse('cathodic', pdur, tsample, 0, pdur)

        # Insert interphase gap if necessary
        gap = np.zeros(int(round(interphase_dur / tsample)))

        # Order the pulses
        if ptype == 'cathodicfirst':
            # has negative current first
            pulse = np.concatenate((off.data, gap), axis=0)
            pulse = np.concatenate((pulse, on.data), axis=0)
        elif ptype == 'anodicfirst':
            pulse = np.concatenate((on.data, gap), axis=0)
            pulse = np.concatenate((pulse, off.data), axis=0)
        else:
            raise ValueError("Acceptable values for `type` are "
                             "'anodicfirst' or 'cathodicfirst'")
        utils.TimeSeries.__init__(self, tsample, pulse)


def image2pulsetrain(img, implant, coding='amplitude', valrange=[0, 50],
                     max_contrast=True, const_amp=20, const_freq=20,
                     rftype='gaussian', rfsize=None, invert=False,
                     tsample=0.005 / 1000, dur=0.5, pulsedur=0.5 / 1000.,
                     interphasedur=0.5 / 1000., pulsetype='cathodicfirst'):
    """Converts an image into a series of pulse trains
    This function creates an input stimulus from an RGB or grayscale image.
    Requires `scikit-image`.
    Parameters
    ----------
    img : str|array_like
        An input image, either a valid filename (string) or a numpy array
        (row x col x channels).
    implant : p2p.implants.ElectrodeArray
        An ElectrodeArray object that describes the implant.
    coding : {'amplitude', 'frequency'}, optional
        A string describing the coding scheme:
        - 'amplitude': Image intensity is linearly converted to a current
                       amplitude between `valrange[0]` and `valrange[1]`.
                       Frequency is held constant at `const_freq`.
        - 'frequency': Image intensity is linearly converted to a pulse
                       frequency between `valrange[0]` and `valrange[1]`.
                       Amplitude is held constant at `const_amp`.
        Default: 'amplitude'
    valrange : list, optional
        Range of stimulation values to be used (If `coding` is 'amplitude',
        specifies min and max current; if `coding` is 'frequency', specifies
        min and max frequency).
        Default: [0, 50]
    max_contrast : bool, optional
        Flag wether to maximize image contrast (True) or not (False).
        Default: True
    const_amp : float, optional
        Constant amplitude value to be sued during frequency coding (only
        relevant when `coding` is 'frequency').
        Default: 20
    const_freq : float, optional
        Constant frequency value to be sued during amplitude coding (only
        relevant when `coding` is 'amplitude').
        Default: 20
    rftype : {'square', 'gaussian'}, optional
        The type of receptive field.
        - 'square': A simple square box receptive field with side length
                    `size`.
        - 'gaussian': A Gaussian receptive field where the weight drops off
                      as a function of distance from the electrode center.
                      The standard deviation of the Gaussian is `size`.
    rfsize : float, optional
        Parameter describing the size of the receptive field. For square
        receptive fields, this corresponds to the side length of the square.
        For Gaussian receptive fields, this corresponds to the standard
        deviation of the Gaussian.
        Default: Twice the `electrode.radius`
    invert : bool, optional
        Flag whether to invert the grayscale values of the image (True) or
        not (False).
        Default: False
    tsample : float, optional
        Sampling time step (seconds). Default: 0.005 / 1000 seconds.
    dur : float, optional
        Stimulus duration (seconds). Default: 0.5 seconds.
    pulsedur : float, optional
        Duration of single (positive or negative) pulse phase in seconds.
    interphasedur : float, optional
        Duration of inter-phase interval (between positive and negative
        pulse) in seconds.
    pulsetype : {'cathodicfirst', 'anodicfirst'}, optional
        A cathodic-first pulse has the negative phase first, whereas an
        anodic-first pulse has the positive phase first.
    """
    try:
        from skimage.io import imread
        from skimage.transform import resize
        from skimage.color import rgb2gray
    except ImportError:
        raise ImportError("You do not have scikit-image installed.")

    # Make sure range of values is valid
    assert len(valrange) == 2 and valrange[1] > valrange[0]

    if not isinstance(implant, implants.ElectrodeArray):
        raise TypeError("implant must be of type implants.ElectrodeArray.")

    if isinstance(img, str):
        # Load image from filename
        img_orig = imread(img, as_grey=True).astype(np.float32)
    else:
        if img.ndim == 2:
            # Grayscale
            img_orig = img.astype(np.float32)
        else:
            # Assume RGB, convert to grayscale
            assert img.shape[-1] == 3
            img_orig = rgb2gray(np.array(img)).astype(np.float32)

    # Make sure all pixels are between 0 and 1
    if img_orig.max() > 1.0:
        img_orig /= 255.0
    assert np.all(img_orig >= 0.0) and np.all(img_orig <= 1.0)

    if invert:
        img_orig = 1.0 - img_orig

    # Center the image on the implant
    xyr = np.array([[e.x_center, e.y_center, e.radius] for e in implant])
    xlo = np.min(xyr[:, 0] - xyr[:, 2])
    xhi = np.max(xyr[:, 0] + xyr[:, 2])
    ylo = np.min(xyr[:, 1] - xyr[:, 2])
    yhi = np.max(xyr[:, 1] + xyr[:, 2])

    # Resize the image accordingly (rows, columns)
    img_resize = resize(img_orig, (yhi - ylo, xhi - xlo))

    # Make a grid that has the image's coordinates on the retina
    yg = np.linspace(ylo, yhi, img_resize.shape[0])
    xg = np.linspace(xlo, xhi, img_resize.shape[1])
    yg, xg = np.meshgrid(yg, xg)

    # For each electrode, find the stimulation strength (magnitude)
    magn = []
    for e in implant:
        rf = e.receptive_field(xg, yg, rftype, rfsize)
        magn.append(np.sum(rf.T * img_resize) / np.sum(rf))
    magn = np.array(magn)

    if max_contrast:
        # Normalize contrast to valrange
        if magn.min() < magn.max():
            magn = (magn - magn.min()) / (magn.max() - magn.min())

    # With `magn` between 0 and 1, now scale to valrange
    magn = magn * np.diff(valrange) + valrange[0]

    # Map magnitude to either freq or amp of pulse train
    pulses = []
    for m in magn:
        if coding == 'amplitude':
            # Map magnitude to amplitude
            amp = m
            freq = const_freq
        elif coding == 'frequency':
            # Map magnitude to frequency
            amp = const_amp
            freq = m
        else:
            e_s = "Acceptable values for `coding` are 'amplitude' or"
            e_s += "'frequency'."
            raise ValueError(e_s)

        pt = PulseTrain(tsample, freq=freq, amp=amp, dur=dur,
                        pulse_dur=pulsedur,
                        interphase_dur=interphasedur,
                        pulsetype=pulsetype)
        pulses.append(pt)

    return pulses


@utils.deprecated
class Movie2Pulsetrain(utils.TimeSeries):
    """
    Is used to create pulse-train stimulus based on luminance over time from
    a movie

    This class is deprecated as of v0.2 and will be replaced with a new
    version in v0.3.
    """

    def __init__(self, rflum, tsample, fps=30.0, amp_transform='linear',
                 amp_max=60, freq=20, pulse_dur=.5 / 1000.,
                 interphase_dur=.5 / 1000.,
                 pulsetype='cathodicfirst', stimtype='pulsetrain'):
        """
        Parameters
        ----------
        rflum : 1D array
           Values between 0 and 1
        tsample : suggest TemporalModel.tsample
        """
        if tsample <= 0:
            raise ValueError("tsample must be a non-negative float.")

        # set up the individual pulses
        pulse = BiphasicPulse(pulsetype, pulse_dur, tsample,
                              interphase_dur)
        # set up the sequence
        dur = rflum.shape[-1] / fps
        if stimtype == 'pulsetrain':
            interpulsegap = np.zeros(int(round((1.0 / freq) / tsample)) -
                                     len(pulse.data))
            ppt = []
            for j in range(0, int(np.ceil(dur * freq))):
                ppt = np.concatenate((ppt, interpulsegap), axis=0)
                ppt = np.concatenate((ppt, pulse.data), axis=0)

        ppt = ppt[0:int(round(dur / tsample))]
        intfunc = spi.interp1d(np.linspace(0, len(rflum), len(rflum)),
                               rflum)

        amp = intfunc(np.linspace(0, len(rflum), len(ppt)))
        data = amp * ppt * amp_max
        utils.TimeSeries.__init__(self, tsample, data)


class PulseTrain(utils.TimeSeries):

    def __init__(self, tsample, freq=20, amp=20, dur=0.5, delay=0,
                 pulse_dur=0.45 / 1000, interphase_dur=0.45 / 1000,
                 pulsetype='cathodicfirst',
                 pulseorder='pulsefirst'):
        """A train of biphasic pulses

        tsample : float
            Sampling interval in seconds parameters, use TemporalModel.tsample.
        ----------
        optional parameters
        freq : float
            Frequency of the pulse envelope in Hz.
        dur : float
            Stimulus duration in seconds.
        pulse_dur : float
            Single-pulse duration in seconds.
        interphase_duration : float
            Single-pulse interphase duration (the time between the positive
            and negative phase) in seconds.
        delay : float
            Delay until stimulus on-set in seconds.
        amp : float
            Max amplitude of the pulse train in micro-amps.
        pulsetype : string
            Pulse type {"cathodicfirst" | "anodicfirst"}, where
            'cathodicfirst' has the negative phase first.
        pulseorder : string
            Pulse order {"gapfirst" | "pulsefirst"}, where
            'pulsefirst' has the pulse first, followed by the gap.
        """
        if tsample <= 0:
            raise ValueError("tsample must be a non-negative float.")

        # Stimulus size given by `dur`
        stim_size = int(np.round(1.0 * dur / tsample))

        # Make sure input is non-trivial, else return all zeros
        if np.isclose(freq, 0) or np.isclose(amp, 0):
            utils.TimeSeries.__init__(self, tsample, np.zeros(stim_size))
            return

        # Envelope size (single pulse + gap) given by `freq`
        # Note that this can be larger than `stim_size`, but we will trim
        # the stimulus to proper length at the very end.
        envelope_size = int(np.round(1.0 / float(freq) / tsample))

        # Delay given by `delay`
        delay_size = int(np.round(1.0 * delay / tsample))

        if delay_size < 0:
            raise ValueError("Delay cannot be negative.")
        delay = np.zeros(delay_size)

        # Single pulse given by `pulse_dur`
        pulse = amp * BiphasicPulse(pulsetype, pulse_dur, tsample,
                                    interphase_dur).data
        pulse_size = pulse.size
        if pulse_size < 0:
            raise ValueError("Single pulse must fit within 1/freq interval.")

        # Then gap is used to fill up what's left
        gap_size = envelope_size - (delay_size + pulse_size)
        if gap_size < 0:
            logging.error("Envelope (%d) can't fit pulse (%d) + delay (%d)" %
                          (envelope_size, pulse_size, delay_size))
            raise ValueError("Pulse and delay must fit within 1/freq "
                             "interval.")
        gap = np.zeros(gap_size)

        pulse_train = np.array([])
        for j in range(int(np.ceil(dur * freq))):
            if pulseorder == 'pulsefirst':
                pulse_train = np.concatenate((pulse_train, delay, pulse,
                                              gap), axis=0)
            elif pulseorder == 'gapfirst':
                pulse_train = np.concatenate((pulse_train, delay, gap,
                                              pulse), axis=0)
            else:
                raise ValueError("Acceptable values for `pulseorder` are "
                                 "'pulsefirst' or 'gapfirst'")

        # If `freq` is not a nice number, the resulting pulse train might not
        # have the desired length
        if pulse_train.size < stim_size:
            fill_size = stim_size - pulse_train.shape[-1]
            pulse_train = np.concatenate((pulse_train, np.zeros(fill_size)),
                                         axis=0)

        # Trim to correct length (takes care of too long arrays, too)
        pulse_train = pulse_train[:stim_size]

        utils.TimeSeries.__init__(self, tsample, pulse_train)


def parse_pulse_trains(stim, implant):
    """Parse input stimulus and convert to list of pulse trains

    Parameters
    ----------
    stim : utils.TimeSeries|list|dict
        There are several ways to specify an input stimulus:

        - For a single-electrode array, pass a single pulse train; i.e., a
          single utils.TimeSeries object.
        - For a multi-electrode array, pass a list of pulse trains, where
          every pulse train is a utils.TimeSeries object; i.e., one pulse
          train per electrode.
        - For a multi-electrode array, specify all electrodes that should
          receive non-zero pulse trains by name in a dictionary. The key
          of each element is the electrode name, the value is a pulse train.
          Example: stim = {'E1': pt, 'stim': pt}, where 'E1' and 'stim' are
          electrode names, and `pt` is a utils.TimeSeries object.
    implant : p2p.implants.ElectrodeArray
        A p2p.implants.ElectrodeArray object that describes the implant.

    Returns
    -------
    A list of pulse trains; one pulse train per electrode.
    """
    # Parse input stimulus
    if isinstance(stim, utils.TimeSeries):
        # `stim` is a single object: This is only allowed if the implant
        # has only one electrode
        if implant.num_electrodes > 1:
            e_s = "More than 1 electrode given, use a list of pulse trains"
            raise ValueError(e_s)
        pt = [copy.deepcopy(stim)]
    elif isinstance(stim, dict):
        # `stim` is a dictionary: Look up electrode names and assign pulse
        # trains, fill the rest with zeros

        # Get right size from first dict element, then generate all zeros
        idx0 = list(stim.keys())[0]
        pt_zero = utils.TimeSeries(stim[idx0].tsample,
                                   np.zeros_like(stim[idx0].data))
        pt = [pt_zero] * implant.num_electrodes

        # Iterate over dictionary and assign non-zero pulse trains to
        # corresponding electrodes
        for key, value in stim.items():
            el_idx = implant.get_index(key)
            if el_idx is not None:
                pt[el_idx] = copy.deepcopy(value)
            else:
                e_s = "Could not find electrode with name '%s'" % key
                raise ValueError(e_s)
    else:
        # Else, `stim` must be a list of pulse trains, one for each electrode
        if len(stim) != implant.num_electrodes:
            e_s = "Number of pulse trains must match number of electrodes"
            raise ValueError(e_s)
        pt = copy.deepcopy(stim)

    return pt


@utils.deprecated
def retinalmovie2electrodtimeseries(rf, movie):
    """
    Calculates the luminance over time for each electrodes receptive field.

    .. deprecated:: 0.1
    """
    rflum = np.zeros(movie.shape[-1])
    for f in range(movie.shape[-1]):
        tmp = rf * movie[:, :, f]
        rflum[f] = np.mean(tmp)

    return rflum
